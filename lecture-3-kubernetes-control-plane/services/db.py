import os
import time

import psycopg
from psycopg.rows import dict_row


def connect():
    return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=3,
                           options="-c statement_timeout=5000", row_factory=dict_row)


def initialize():
    # A transaction-level advisory lock serializes schema creation by replicas.
    for attempt in range(60):
        try:
            with connect() as conn:
                conn.execute("SELECT pg_advisory_xact_lock(300030)")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS orders (
                        id BIGSERIAL PRIMARY KEY,
                        item TEXT NOT NULL,
                        quantity INTEGER NOT NULL CHECK (quantity > 0),
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        processed_at TIMESTAMPTZ,
                        processed_by TEXT
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS orders_pending ON orders (id) WHERE processed_at IS NULL")
            return
        except psycopg.OperationalError:
            if attempt == 59:
                raise
            time.sleep(2)
