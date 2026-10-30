import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from db import connect, initialize

REQUESTS = Counter("shop_http_requests_total", "API responses", ["method", "path", "code"])
DURATION = Histogram("shop_http_request_duration_seconds", "API request latency", ["method", "path"])


@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(initialize)
    yield


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def metrics(request: Request, call_next):
    start = time.monotonic()
    code = 500
    path = request.url.path if request.url.path in {"/health", "/order", "/orders", "/metrics"} else "other"
    try:
        response = await call_next(request)
        code = response.status_code
        response.headers["X-Shop-Version"] = os.getenv("APP_VERSION", "1.0.0")
        return response
    finally:
        if path != "/metrics":
            REQUESTS.labels(request.method, path, str(code)).inc()
            DURATION.labels(request.method, path).observe(time.monotonic() - start)


@app.exception_handler(psycopg.Error)
async def database_error(request, exc):
    logging.exception("Database operation failed", exc_info=exc)
    return PlainTextResponse("database unavailable", status_code=503)


@app.get("/health", response_class=PlainTextResponse)
def health():
    # Liveness deliberately does not depend on the database.
    if os.getenv("HEALTH_FAIL", "false").lower() == "true":
        raise HTTPException(503, "forced health failure")
    return "ok"


class Order(BaseModel):
    item: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=1, ge=1, le=1000000)


@app.post("/order", status_code=201)
def create_order(order: Order):
    with connect() as conn:
        return conn.execute(
            "INSERT INTO orders (item, quantity) VALUES (%s, %s) RETURNING *",
            (order.item, order.quantity),
        ).fetchone()


@app.get("/orders")
def list_orders():
    with connect() as conn:
        return conn.execute("SELECT * FROM orders ORDER BY id").fetchall()


@app.get("/metrics")
def metrics_endpoint():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
