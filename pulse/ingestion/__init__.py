"""Data ingestion package for scraping and normalizing Play Store reviews."""

import logging
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from pulse.ingestion.models import RawReview, Review, RunContext
from pulse.ingestion.play_store import fetch_reviews
from pulse.ingestion.normalizer import normalize_reviews
from pulse.ingestion.cache import save_to_cache, load_from_cache, load_raw_from_cache

logger = logging.getLogger(__name__)


def fetch_and_cache_reviews(
    product_config: Dict[str, Any],
    run_context: RunContext,
    date_str: Optional[str] = None,
    base_dir: str = "data/cache",
) -> List[Review]:
    """Fetch reviews from Play Store (or cache) and return quality-filtered pipeline inputs."""
    product = run_context.product
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Step 1: Check cache first
    cached = load_from_cache(product, date_str, base_dir=base_dir)
    if cached is not None:
        logger.info(f"Using {len(cached)} normalized reviews from cache for {product} ({date_str}).")
        return cached

    # Step 2: Fallback to live scrape
    play_store_cfg = product_config.get("play_store", {})
    app_id = play_store_cfg.get("app_id")
    if not app_id:
        raise ValueError(f"No play_store.app_id defined for product '{product}' in config.")

    ingestion_cfg = product_config.get("ingestion", {})
    window_weeks = getattr(run_context, "window_weeks", ingestion_cfg.get("window_weeks", 10))
    max_reviews = ingestion_cfg.get("max_reviews", 5000)
    min_words = ingestion_cfg.get("min_words", 8)
    allowed_lang = ingestion_cfg.get("allowed_language", "en")

    logger.info(f"Cache miss for {product} ({date_str}). Starting live scrape for {app_id}...")
    start_time = time.time()
    try:
        raw_reviews = fetch_reviews(
            app_id=app_id, window_weeks=window_weeks, max_reviews=max_reviews
        )
    except Exception as e:
        logger.error(f"Ingestion failed during Play Store scrape for {app_id}: {e}")
        raise

    duration = time.time() - start_time

    # Step 3: Normalize and filter
    normalized_reviews = normalize_reviews(
        raw_reviews, min_words=min_words, allowed_language=allowed_lang
    )

    # Step 4: Save to cache
    save_to_cache(
        product=product,
        raw_reviews=raw_reviews,
        normalized_reviews=normalized_reviews,
        date_str=date_str,
        window_weeks=window_weeks,
        scrape_duration=duration,
        base_dir=base_dir,
    )

    return normalized_reviews


__all__ = [
    "RawReview",
    "Review",
    "RunContext",
    "fetch_reviews",
    "normalize_reviews",
    "save_to_cache",
    "load_from_cache",
    "load_raw_from_cache",
    "fetch_and_cache_reviews",
]
