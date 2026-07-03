"""Google Play Store scraper module (Phase 1)."""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Any
from google_play_scraper import Sort, reviews
from pulse.ingestion.models import RawReview

logger = logging.getLogger(__name__)


def _fetch_page_with_retry(
    app_id: str,
    count: int = 100,
    continuation_token: Optional[Any] = None,
    max_retries: int = 3,
) -> tuple[list, Any]:
    """Fetch a page of reviews with exponential backoff retry."""
    for attempt in range(1, max_retries + 1):
        try:
            result, token = reviews(
                app_id,
                lang="en",
                country="us",
                sort=Sort.NEWEST,
                count=count,
                continuation_token=continuation_token,
            )
            return result, token
        except Exception as e:
            logger.warning(
                f"Error fetching Play Store reviews for {app_id} (attempt {attempt}/{max_retries}): {e}"
            )
            if attempt == max_retries:
                logger.error(f"Failed to fetch reviews for {app_id} after {max_retries} attempts.")
                raise
            time.sleep(2 ** attempt)
    return [], None


def fetch_reviews(
    app_id: str, window_weeks: int = 10, max_reviews: int = 5000
) -> List[RawReview]:
    """Scrape public reviews from Google Play Store within the specified rolling date window."""
    logger.info(f"Starting review scrape for app_id={app_id}, window_weeks={window_weeks}, max_reviews={max_reviews}")
    
    cutoff_dt = datetime.now(timezone.utc) - timedelta(weeks=window_weeks)
    raw_reviews: List[RawReview] = []
    continuation_token = None
    batch_size = 100
    reached_cutoff = False

    while len(raw_reviews) < max_reviews and not reached_cutoff:
        count = min(batch_size, max_reviews - len(raw_reviews))
        result, continuation_token = _fetch_page_with_retry(
            app_id, count=count, continuation_token=continuation_token
        )

        if not result:
            logger.info("No more reviews returned from store.")
            break

        for item in result:
            text = item.get("content", "")
            rating = item.get("score", 0)
            pub_dt = item.get("at")

            if not pub_dt:
                continue

            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)

            if pub_dt < cutoff_dt:
                reached_cutoff = True
                break

            if len(raw_reviews) < max_reviews:
                raw_reviews.append(
                    RawReview(
                        text=text.strip(),
                        rating=int(rating),
                        published_at=pub_dt.isoformat(),
                    )
                )

        logger.debug(f"Fetched {len(raw_reviews)} reviews so far...")
        
        if not continuation_token or reached_cutoff:
            break

        time.sleep(1.0)  # Rate limiting between pagination requests

    logger.info(f"Completed scrape: fetched {len(raw_reviews)} raw reviews.")
    return raw_reviews
