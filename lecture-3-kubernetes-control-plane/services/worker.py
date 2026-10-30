import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

from db import connect, initialize

PROCESSED = Counter("shop_orders_processed_total", "Orders processed by this worker")
ERRORS = Counter("shop_worker_errors_total", "Worker database errors")
LAST_SUCCESS = Gauge("shop_worker_last_success_timestamp_seconds", "Last successful database poll")
last_poll = 0.0


def process_one():
    with connect() as conn:
        return conn.execute("""
            WITH candidate AS (
                SELECT id FROM orders WHERE processed_at IS NULL
                ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED
            )
            UPDATE orders SET processed_at = now(), processed_by = %s
            FROM candidate WHERE orders.id = candidate.id RETURNING orders.id
        """, (os.getenv("HOSTNAME", "worker"),)).fetchone()


async def run():
    global last_poll
    while True:
        try:
            order = await asyncio.to_thread(process_one)
            last_poll = time.monotonic()
            LAST_SUCCESS.set_to_current_time()
            if order:
                PROCESSED.inc()
                logging.info("Processed order %s", order["id"])
            else:
                await asyncio.sleep(1)
        except Exception:
            ERRORS.inc()
            logging.exception("Worker poll failed; retrying")
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(initialize)
    task = asyncio.create_task(run())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(lifespan=lifespan)


@app.get("/health", response_class=PlainTextResponse)
def health():
    if os.getenv("HEALTH_FAIL", "false").lower() == "true" or time.monotonic() - last_poll > 30:
        raise HTTPException(503, "worker has no recent successful poll")
    return "ok"


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
