"""ML and NLP analysis pipeline package."""

from datetime import datetime, timezone
import logging
from typing import List, Dict, Any, Optional
from pulse.ingestion.models import Review, RunContext
from pulse.pipeline.scrubber import is_latin_dominant, filter_scripts, scrub_pii
from pulse.pipeline.embeddings import generate_embeddings
from pulse.pipeline.clustering import cluster_reviews
from pulse.pipeline.summarizer import summarize_clusters, stratified_sample
from pulse.pipeline.quote_validator import validate_quotes, ActionIdea, Theme, PulseReport

logger = logging.getLogger(__name__)

__all__ = [
    "is_latin_dominant",
    "filter_scripts",
    "scrub_pii",
    "generate_embeddings",
    "cluster_reviews",
    "summarize_clusters",
    "stratified_sample",
    "validate_quotes",
    "ActionIdea",
    "Theme",
    "PulseReport",
    "run_pipeline",
]


def run_pipeline(
    reviews: List[Review],
    config: Dict[str, Any],
    run_context: RunContext,
    client: Optional[Any] = None,
) -> PulseReport:
    """Execute the full Phase 2 analysis pipeline: scrub -> embed -> cluster -> summarize -> validate."""
    logger.info(f"Starting Phase 2 analysis pipeline for product={run_context.product} with {len(reviews)} reviews.")

    # 1. Script filtering
    latin_reviews = filter_scripts(reviews)

    # 2. PII Scrubbing
    scrubbed_reviews = scrub_pii(latin_reviews)

    # ML Floor check
    min_reviews = config.get("ingestion", {}).get("min_reviews", 20)
    if len(scrubbed_reviews) < min_reviews:
        raise ValueError(
            f"Insufficient reviews for ML analysis: count={len(scrubbed_reviews)} < {min_reviews} after filtering/scrubbing."
        )

    # 3. Embeddings
    embed_cfg = config.get("embedding", {})
    model_name = embed_cfg.get("model", "BAAI/bge-small-en-v1.5")
    batch_size = embed_cfg.get("batch_size", 64)
    embeddings = generate_embeddings(
        scrubbed_reviews, model_name=model_name, batch_size=batch_size, min_reviews=min_reviews
    )

    # 4. Clustering
    clusters = cluster_reviews(scrubbed_reviews, embeddings, config)

    # 5. Summarization
    raw_themes = summarize_clusters(clusters, scrubbed_reviews, config=config, client=client)

    # 6. Quote Validation
    validated_themes = validate_quotes(raw_themes, scrubbed_reviews)

    report = PulseReport(
        product=run_context.product,
        iso_week=run_context.iso_week,
        window_weeks=run_context.window_weeks,
        review_count=len(scrubbed_reviews),
        themes=validated_themes,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    logger.info(
        f"Pipeline completed successfully: generated report with {len(validated_themes)} validated themes."
    )
    return report
