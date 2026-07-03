"""Caching layer for scraped and normalized reviews (Phase 1)."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from pulse.ingestion.models import RawReview, Review

logger = logging.getLogger(__name__)


def _get_cache_dir(product: str, date_str: str, base_dir: str = "data/cache") -> str:
    """Resolve cache directory path: data/cache/{product}/{date}/."""
    return os.path.join(base_dir, product, date_str)


def save_to_cache(
    product: str,
    raw_reviews: List[RawReview],
    normalized_reviews: List[Review],
    date_str: Optional[str] = None,
    window_weeks: int = 10,
    scrape_duration: float = 0.0,
    base_dir: str = "data/cache",
) -> str:
    """Write raw and normalized reviews and metadata manifest to disk."""
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    cache_dir = _get_cache_dir(product, date_str, base_dir=base_dir)
    os.makedirs(cache_dir, exist_ok=True)

    raw_path = os.path.join(cache_dir, "reviews_raw.json")
    norm_path = os.path.join(cache_dir, "reviews_normalized.json")
    manifest_path = os.path.join(cache_dir, "manifest.json")

    # Save raw reviews
    raw_data = [
        {
            "text": r.text,
            "rating": r.rating,
            "published_at": r.published_at,
        }
        for r in raw_reviews
    ]
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)

    # Save normalized reviews
    norm_data = [
        {
            "text": r.text,
            "rating": r.rating,
        }
        for r in normalized_reviews
    ]
    with open(norm_path, "w", encoding="utf-8") as f:
        json.dump(norm_data, f, ensure_ascii=False, indent=2)

    # Save manifest
    manifest: Dict[str, Any] = {
        "product": product,
        "fetch_date": date_str,
        "window_weeks": window_weeks,
        "raw_count": len(raw_reviews),
        "normalized_count": len(normalized_reviews),
        "scrape_duration_seconds": round(scrape_duration, 2),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    logger.info(f"Saved cache for product={product}, date={date_str} in {cache_dir}")
    return cache_dir


def load_from_cache(
    product: str, date_str: str, base_dir: str = "data/cache"
) -> Optional[List[Review]]:
    """Load normalized reviews from cache if available."""
    cache_dir = _get_cache_dir(product, date_str, base_dir=base_dir)
    norm_path = os.path.join(cache_dir, "reviews_normalized.json")

    if not os.path.exists(norm_path):
        logger.debug(f"Cache miss: no normalized reviews found at {norm_path}")
        return None

    try:
        with open(norm_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        reviews = [Review(text=item["text"], rating=item["rating"]) for item in data]
        logger.info(f"Loaded {len(reviews)} normalized reviews from cache ({norm_path}).")
        return reviews
    except Exception as e:
        logger.error(f"Error loading cache from {norm_path}: {e}")
        return None


def load_raw_from_cache(
    product: str, date_str: str, base_dir: str = "data/cache"
) -> Optional[List[RawReview]]:
    """Load raw reviews from cache if available."""
    cache_dir = _get_cache_dir(product, date_str, base_dir=base_dir)
    raw_path = os.path.join(cache_dir, "reviews_raw.json")

    if not os.path.exists(raw_path):
        return None

    try:
        with open(raw_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        reviews = [
            RawReview(
                text=item["text"],
                rating=item["rating"],
                published_at=item["published_at"],
            )
            for item in data
        ]
        return reviews
    except Exception as e:
        logger.error(f"Error loading raw cache from {raw_path}: {e}")
        return None
