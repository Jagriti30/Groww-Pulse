"""SQLite ledger storage and idempotency check module (Phase 6)."""

import os
import sqlite3
from typing import Optional, List
from pulse.ledger.models import RunRecord, DeliveryRecord


class LedgerStore:
    """SQLite-backed ledger for recording runs and checking idempotency constraints."""

    def __init__(self, db_path: str = "data/ledger.db"):
        self.db_path = db_path

    def _get_conn(self) -> sqlite3.Connection:
        if os.path.dirname(self.db_path):
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Initialize runs and deliveries tables if they do not exist."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    product TEXT NOT NULL,
                    iso_week TEXT NOT NULL,
                    status TEXT NOT NULL,
                    review_count INTEGER NOT NULL,
                    window_weeks INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    error_message TEXT,
                    report_json TEXT
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS deliveries (
                    run_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    idempotency_key TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
            """)
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_completed_runs
                ON runs (product, iso_week) WHERE status = 'completed';
            """)

    def check_completed_run(self, product: str, iso_week: str) -> Optional[RunRecord]:
        """Check if an idempotent run has already completed for the given product and week."""
        self.init_db()
        with self._get_conn() as conn:
            cursor = conn.execute("""
                SELECT * FROM runs
                WHERE product = ? AND iso_week = ? AND status = 'completed'
                ORDER BY completed_at DESC LIMIT 1
            """, (product, iso_week))
            row = cursor.fetchone()
            if row:
                return RunRecord(
                    run_id=row["run_id"],
                    product=row["product"],
                    iso_week=row["iso_week"],
                    status=row["status"],
                    review_count=row["review_count"],
                    window_weeks=row["window_weeks"],
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                    error_message=row["error_message"],
                    report_json=row["report_json"]
                )
        return None

    def record_run(self, run: RunRecord, deliveries: List[DeliveryRecord]):
        """Persist a run and its associated deliveries in a transaction."""
        self.init_db()
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO runs (
                    run_id, product, iso_week, status, review_count,
                    window_weeks, started_at, completed_at, error_message, report_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run.run_id, run.product, run.iso_week, run.status, run.review_count,
                run.window_weeks, run.started_at, run.completed_at, run.error_message, run.report_json
            ))

            conn.execute("DELETE FROM deliveries WHERE run_id = ?", (run.run_id,))
            for d in deliveries:
                conn.execute("""
                    INSERT INTO deliveries (run_id, channel, external_id, url, idempotency_key)
                    VALUES (?, ?, ?, ?, ?)
                """, (d.run_id, d.channel, d.external_id, d.url, d.idempotency_key))

    def get_runs(self, product: str, iso_week: Optional[str] = None) -> List[RunRecord]:
        """Fetch runs for a product, optionally filtered by ISO week."""
        self.init_db()
        with self._get_conn() as conn:
            if iso_week:
                cursor = conn.execute("""
                    SELECT * FROM runs WHERE product = ? AND iso_week = ? ORDER BY started_at DESC
                """, (product, iso_week))
            else:
                cursor = conn.execute("""
                    SELECT * FROM runs WHERE product = ? ORDER BY started_at DESC
                """, (product,))
            rows = cursor.fetchall()
            return [
                RunRecord(
                    run_id=r["run_id"],
                    product=r["product"],
                    iso_week=r["iso_week"],
                    status=r["status"],
                    review_count=r["review_count"],
                    window_weeks=r["window_weeks"],
                    started_at=r["started_at"],
                    completed_at=r["completed_at"],
                    error_message=r["error_message"],
                    report_json=r["report_json"]
                ) for r in rows
            ]

    def get_deliveries(self, run_id: str) -> List[DeliveryRecord]:
        """Fetch all delivery records associated with a run ID."""
        self.init_db()
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM deliveries WHERE run_id = ?", (run_id,))
            rows = cursor.fetchall()
            return [
                DeliveryRecord(
                    run_id=r["run_id"],
                    channel=r["channel"],
                    external_id=r["external_id"],
                    url=r["url"],
                    idempotency_key=r["idempotency_key"]
                ) for r in rows
            ]
