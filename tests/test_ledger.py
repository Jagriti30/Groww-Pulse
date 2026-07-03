"""Unit tests for Phase 6 SQLite ledger and audit store."""

import os
import sqlite3
import pytest
from datetime import datetime, timezone
from pulse.ledger.models import RunRecord, DeliveryRecord
from pulse.ledger.store import LedgerStore


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_ledger.db"
    store = LedgerStore(db_path=str(db_file))
    store.init_db()
    return store


def test_ledger_init_and_empty_check(test_db):
    assert test_db.check_completed_run("groww", "2026-W23") is None
    assert test_db.get_runs("groww") == []


def test_ledger_record_and_retrieve_run(test_db):
    now = datetime.now(timezone.utc).isoformat()
    run = RunRecord(
        run_id="run-123",
        product="groww",
        iso_week="2026-W23",
        status="completed",
        review_count=100,
        window_weeks=10,
        started_at=now,
        completed_at=now,
        report_json='{"test": true}'
    )
    deliveries = [
        DeliveryRecord(run_id="run-123", channel="google_doc", external_id="h.123", url="http://doc", idempotency_key="groww-2026-W23"),
        DeliveryRecord(run_id="run-123", channel="gmail", external_id="draft-456", url="http://mail", idempotency_key="groww-2026-W23-email")
    ]
    test_db.record_run(run, deliveries)

    # Check idempotency lookup
    completed = test_db.check_completed_run("groww", "2026-W23")
    assert completed is not None
    assert completed.run_id == "run-123"
    assert completed.status == "completed"
    assert completed.review_count == 100

    # Check queries
    runs = test_db.get_runs("groww", "2026-W23")
    assert len(runs) == 1
    assert runs[0].run_id == "run-123"

    saved_deliveries = test_db.get_deliveries("run-123")
    assert len(saved_deliveries) == 2
    channels = {d.channel: d.url for d in saved_deliveries}
    assert channels["google_doc"] == "http://doc"
    assert channels["gmail"] == "http://mail"


def test_ledger_partial_failure_not_idempotent(test_db):
    now = datetime.now(timezone.utc).isoformat()
    run = RunRecord(
        run_id="run-fail",
        product="groww",
        iso_week="2026-W24",
        status="failed",
        review_count=50,
        window_weeks=10,
        started_at=now,
        error_message="Gmail delivery failed"
    )
    test_db.record_run(run, [])

    # Since status is 'failed', check_completed_run should return None (allowing retry)
    assert test_db.check_completed_run("groww", "2026-W24") is None

    runs = test_db.get_runs("groww", "2026-W24")
    assert len(runs) == 1
    assert runs[0].status == "failed"
