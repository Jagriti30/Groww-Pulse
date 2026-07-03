"""Data models for SQLite run ledger and audit log."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class RunRecord:
    run_id: str
    product: str
    iso_week: str
    status: str            # "pending" | "completed" | "failed"
    review_count: int
    window_weeks: int
    started_at: str
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    report_json: Optional[str] = None


@dataclass
class DeliveryRecord:
    run_id: str
    channel: str           # "google_doc" | "gmail"
    external_id: str       # heading_id, message_id, draft_id
    url: str
    idempotency_key: Optional[str] = None
