"""Unit tests for Phase 1 (Play Store ingestion, normalization, and caching)."""

import json
import os
from unittest.mock import patch
import pytest
from pulse.ingestion.models import RawReview, Review, RunContext
from pulse.ingestion import (
    normalize_reviews,
    save_to_cache,
    load_from_cache,
    load_raw_from_cache,
    fetch_and_cache_reviews,
)


def test_normalize_reviews_filtering_and_dedup():
    raw_list = [
        # Valid review (≥ 8 words)
        RawReview(text="This is a very good app for beginners in investing.", rating=5, published_at="2026-06-01T10:00:00Z"),
        # Duplicate of the first one
        RawReview(text="This is a very good app for beginners in investing.", rating=5, published_at="2026-06-01T10:00:00Z"),
        # Too short (< 8 words)
        RawReview(text="Good app liked it.", rating=4, published_at="2026-06-02T10:00:00Z"),
        # Emoji-only
        RawReview(text="🔥🔥🔥😀😀😀", rating=5, published_at="2026-06-03T10:00:00Z"),
        # Valid with emoji and extra whitespace
        RawReview(text="  Great platform for mutual funds and stocks investment!! 🔥  ", rating=5, published_at="2026-06-04T10:00:00Z"),
    ]

    normalized = normalize_reviews(raw_list, min_words=8)
    
    assert len(normalized) == 2
    assert normalized[0].text == "This is a very good app for beginners in investing."
    assert normalized[0].rating == 5
    assert normalized[1].text == "Great platform for mutual funds and stocks investment!! 🔥"
    assert normalized[1].rating == 5


def test_cache_save_and_load(tmp_path):
    base_dir = str(tmp_path)
    product = "test_product"
    date_str = "2026-07-02"

    raw = [RawReview(text="Awesome app for daily trading and investment.", rating=5, published_at="2026-07-01T12:00:00Z")]
    norm = [Review(text="Awesome app for daily trading and investment.", rating=5)]

    save_to_cache(product, raw, norm, date_str=date_str, window_weeks=10, scrape_duration=1.5, base_dir=base_dir)

    # Check manifest exists and is valid
    manifest_path = os.path.join(base_dir, product, date_str, "manifest.json")
    assert os.path.exists(manifest_path)
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["product"] == product
    assert manifest["raw_count"] == 1
    assert manifest["normalized_count"] == 1

    # Check load_from_cache
    loaded_norm = load_from_cache(product, date_str, base_dir=base_dir)
    assert loaded_norm is not None
    assert len(loaded_norm) == 1
    assert loaded_norm[0].text == norm[0].text
    assert loaded_norm[0].rating == 5

    # Check load_raw_from_cache
    loaded_raw = load_raw_from_cache(product, date_str, base_dir=base_dir)
    assert loaded_raw is not None
    assert len(loaded_raw) == 1
    assert loaded_raw[0].published_at == raw[0].published_at


@patch("pulse.ingestion.fetch_reviews")
def test_fetch_and_cache_reviews(mock_fetch, tmp_path):
    base_dir = str(tmp_path)
    product_cfg = {
        "product": "groww",
        "play_store": {"app_id": "com.nextbillion.groww"},
        "ingestion": {"window_weeks": 10, "min_words": 8},
    }
    run_ctx = RunContext(product="groww", iso_week="2026-W23", window_weeks=10, dry_run=False, email_mode="draft")

    mock_fetch.return_value = [
        RawReview(text="This application is really wonderful for stock market investing.", rating=5, published_at="2026-06-01T10:00:00Z"),
        RawReview(text="Short review", rating=3, published_at="2026-06-02T10:00:00Z"),
    ]

    # First call: cache miss, invokes live scrape mock
    results = fetch_and_cache_reviews(product_cfg, run_ctx, date_str="2026-07-02", base_dir=base_dir)
    assert len(results) == 1
    assert results[0].text == "This application is really wonderful for stock market investing."
    mock_fetch.assert_called_once_with(app_id="com.nextbillion.groww", window_weeks=10, max_reviews=5000)

    # Second call: cache hit, should not invoke fetch_reviews again
    mock_fetch.reset_mock()
    results_cached = fetch_and_cache_reviews(product_cfg, run_ctx, date_str="2026-07-02", base_dir=base_dir)
    assert len(results_cached) == 1
    assert results_cached[0].text == results[0].text
    mock_fetch.assert_not_called()
