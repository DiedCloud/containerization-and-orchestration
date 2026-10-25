"""api — the service under observation for Lab 2.

Endpoints:
    GET /health   -> "ok"
    GET /fail     -> 500 and the error counter grows
    GET /slow     -> sleeps 1..3 s inside a nested "slow-op" span
    GET /load     -> fires a burst of requests at itself (?n=, default 50)
    GET /metrics  -> Prometheus exposition (RED: requests, errors, latency histogram)

Wiring of the three pillars:
    metrics -> prometheus_client, scraped by Prometheus (pull model)
    logs    -> structured JSON on stdout; every line carries the current trace_id
    traces  -> OpenTelemetry, exported over OTLP to Jaeger

All three are configured in this one process, on purpose: that is what
"instrumentation" means — the service emits signals about itself.
"""

import asyncio
import json
import logging
import os
import random
import time
import sys
from datetime import datetime, timezone

import httpx
import uvicorn
from fastapi import FastAPI, Response
from fastapi.responses import PlainTextResponse, JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

PORT = int(os.getenv("PORT", "8080"))
METRICS_PATH = "/metrics"
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "api")


# --------------------------------------------------------------------------
# Tracing: provider + OTLP export to Jaeger (set up before the app is built)
# --------------------------------------------------------------------------
def _setup_tracing() -> None:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    # BatchSpanProcessor buffers spans and ships them in the background:
    # a request must not block on the tracing backend being up.
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(provider)


_setup_tracing()
tracer = trace.get_tracer(SERVICE_NAME)


# --------------------------------------------------------------------------
# Logging: JSON on stdout, trace_id pulled from the *current* span context.
# Because the trace/span id lives in a contextvar, the handler can enrich
# every record without the caller passing ids around by hand.
# --------------------------------------------------------------------------
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        ctx = trace.get_current_span().get_span_context()
        if ctx.is_valid:
            payload["trace_id"] = format(ctx.trace_id, "032x")
            payload["span_id"] = format(ctx.span_id, "016x")
        payload.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
root = logging.getLogger()
root.handlers = [handler]
root.setLevel(logging.INFO)
log = logging.getLogger(SERVICE_NAME)


# --------------------------------------------------------------------------
# Metrics: the RED signals (Rate, Errors, Duration) of this service
# --------------------------------------------------------------------------
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests handled.",
    ["method", "route", "code", "source"],
)
http_errors_total = Counter(
    "http_errors_total",
    "Total HTTP requests that ended in a 5xx.",
    ["method", "route", "code", "source"],
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "route", "source"],
    # Buckets are the point of a histogram: they let Prometheus compute any
    # quantile (p95, p99) later. A stored average could never do that.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0),
)

# Fixed routes only: keeps label cardinality bounded (never label by raw URL).
ROUTE_LABELS = {"/health", "/fail", "/slow", "/load"}


class RequestMetricsMiddleware:
    """Pure ASGI middleware: counts every request and logs one JSON line.

    Deliberately NOT BaseHTTPMiddleware — that one runs the app in a separate
    task, which historically breaks OTel context propagation.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == METRICS_PATH:
            # Scrapes of /metrics are Prometheus talking to us, not user
            # traffic — counting them would pollute the RED dashboard.
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "")
        route = path if path in ROUTE_LABELS else "other"
        headers = dict(scope.get("headers", []))
        # Lab classification only, not a security boundary: clients can spoof
        # headers. Never put arbitrary header values into metric labels.
        if path == "/health" and headers.get(b"user-agent", b"").startswith(b"kube-probe/"):
            source = "kubernetes_probe"
        elif headers.get(b"x-lab-traffic-source") == b"load_generator":
            source = "load_generator"
        else:
            source = "client"
        started = time.perf_counter()
        status = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - started
            code = str(status["code"])
            http_requests_total.labels(method, route, code, source).inc()
            http_request_duration_seconds.labels(method, route, source).observe(duration)
            if code.startswith("5"):
                http_errors_total.labels(method, route, code, source).inc()
            log.info(
                "request",
                extra={
                    "extra_fields": {
                        "method": method,
                        "route": route,
                        "source": source,
                        "code": status["code"],
                        "duration_ms": round(duration * 1000, 2),
                    }
                },
            )


app = FastAPI(title=SERVICE_NAME)

# Ordering matters: middleware added first ends up *inside* the stack, and the
# OTel middleware is added later (by FastAPIInstrumentor) so it becomes the
# outermost one. That way the server span is already current when our
# middleware logs — hence every request line has a real trace_id.
app.add_middleware(RequestMetricsMiddleware)
FastAPIInstrumentor.instrument_app(app)   # root span per incoming request
HTTPXClientInstrumentor().instrument()    # outgoing calls join the same trace


@app.get(METRICS_PATH, include_in_schema=False)
async def metrics():
    # generate_latest() serialises the whole registry into the Prometheus text
    # format. Serving it as a plain route (rather than mounting a sub-app at
    # /metrics) avoids Starlette's 307 redirect /metrics -> /metrics/.
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health():
    return PlainTextResponse("ok")


@app.get("/fail")
async def fail():
    span = trace.get_current_span()
    err = RuntimeError("simulated failure (alerting demo)")
    span.record_exception(err)
    span.set_status(Status(StatusCode.ERROR, "simulated failure"))
    log.error("simulated failure", extra={"extra_fields": {"route": "/fail"}})
    return JSONResponse(status_code=500, content={"error": "simulated failure"})


@app.get("/slow")
async def slow():
    delay = random.uniform(1.0, 3.0)
    # A nested span makes the waterfall self-explanatory: the root span is the
    # request, "slow-op" is where the time actually went.
    with tracer.start_as_current_span("slow-op") as span:
        span.set_attribute("slow.delay_seconds", round(delay, 3))
        log.info("slow-op start", extra={"extra_fields": {"delay_s": round(delay, 3)}})
        await asyncio.sleep(delay)
    log.info("slow-op done", extra={"extra_fields": {"delay_s": round(delay, 3)}})
    return {"slept_seconds": round(delay, 3)}


@app.get("/load")
async def load(n: int = 50):
    base = f"http://127.0.0.1:{PORT}"
    async with httpx.AsyncClient(
        base_url=base,
        timeout=10.0,
        headers={"X-Lab-Traffic-Source": "load_generator"},
    ) as client:
        results = await asyncio.gather(
            *(client.get("/health") for _ in range(n)), return_exceptions=True
        )
    ok = sum(1 for r in results if not isinstance(r, Exception) and r.status_code == 200)
    log.info(
        "load burst done",
        extra={"extra_fields": {"requested": n, "ok": ok}},
    )
    return {"requested": n, "ok": ok}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, access_log=False)
