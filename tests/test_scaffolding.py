"""Unit tests for Phase 0 scaffolding."""

import os
import yaml
from pulse.ingestion.models import RawReview, Review, RunContext


def test_models_importable():
    raw = RawReview(text="Good app", rating=5, published_at="2026-06-01T10:00:00Z")
    review = Review(text="Good app", rating=5)
    ctx = RunContext(product="groww", iso_week="2026-W23", window_weeks=10, dry_run=False, email_mode="draft")
    assert raw.rating == 5
    assert review.text == "Good app"
    assert ctx.product == "groww"


def test_configs_loadable():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    groww_path = os.path.join(base_dir, "config", "products", "groww.yaml")
    pipeline_path = os.path.join(base_dir, "config", "pipeline.yaml")
    
    with open(groww_path, "r", encoding="utf-8") as f:
        groww_cfg = yaml.safe_load(f)
    assert groww_cfg["product"] == "groww"
    assert groww_cfg["ingestion"]["window_weeks"] == 10
    
    with open(pipeline_path, "r", encoding="utf-8") as f:
        pipeline_cfg = yaml.safe_load(f)
    assert pipeline_cfg["embedding"]["provider"] == "sentence-transformers"
