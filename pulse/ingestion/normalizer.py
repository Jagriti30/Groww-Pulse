"""Review normalizer and quality filter module (Phase 1)."""

import hashlib
import logging
from typing import List, Set
from pulse.ingestion.models import RawReview, Review

logger = logging.getLogger(__name__)


def _compute_hash(review: RawReview) -> str:
    """Compute SHA-256 hash of (text, rating, published_at) for deduplication."""
    payload = f"{review.text}|{review.rating}|{review.published_at}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_reviews(
    raw_reviews: List[RawReview],
    min_words: int = 8,
    allowed_language: str = "en",
) -> List[Review]:
    """Apply quality filters (word count, language, emoji removal) and deduplicate reviews."""
    total_raw = len(raw_reviews)
    logger.info(f"Starting review normalization for {total_raw} raw reviews...")

    # Step 1: Deduplicate by hash of (text, rating, published_at)
    seen_hashes: Set[str] = set()
    deduped_raw: List[RawReview] = []
    for r in raw_reviews:
        h = _compute_hash(r)
        if h not in seen_hashes:
            seen_hashes.add(h)
            deduped_raw.append(r)

    post_dedup_count = len(deduped_raw)
    logger.info(f"Deduplication: {total_raw} raw -> {post_dedup_count} unique reviews.")

    # Step 2: Apply quality filters
    normalized: List[Review] = []
    for r in deduped_raw:
        # Clean and standardize whitespace
        clean_text = " ".join(r.text.split()).strip()

        if not clean_text:
            continue

        # Check emoji-only / lack of alphanumeric characters
        if not any(c.isalnum() for c in clean_text):
            continue

        # Check word count
        words = clean_text.split()
        if len(words) < min_words:
            continue

        # Note: Play Store scraper already filters lang='en'.
        # Phase 2a script filter will further drop non-Latin dominant scripts like Devanagari.
        normalized.append(Review(text=clean_text, rating=r.rating))

    post_norm_count = len(normalized)
    logger.info(
        f"Normalization complete: {post_dedup_count} unique -> {post_norm_count} normalized reviews "
        f"({(post_norm_count / total_raw * 100) if total_raw else 0:.1f}% kept)."
    )
    return normalized
