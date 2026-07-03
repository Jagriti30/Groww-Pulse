"""Core data models for Play Store review ingestion and pipeline processing."""

from dataclasses import dataclass


@dataclass
class RawReview:
    """Raw review payload scraped directly from the store."""
    text: str
    rating: int          # 1–5 stars
    published_at: str    # ISO datetime UTC


@dataclass
class Review:
    """Normalized review after passing quality filters (word count, language, emoji)."""
    text: str            # Normalized, quality-filtered
    rating: int          # 1–5 stars


@dataclass
class RunContext:
    """Execution context and parameters for a pulse run."""
    product: str
    iso_week: str        # e.g. "2026-W23"
    window_weeks: int
    dry_run: bool
    email_mode: str      # "draft" | "send"
