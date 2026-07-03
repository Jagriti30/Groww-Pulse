"""Local sentence-transformers embedding generation module (Phase 2)."""

import hashlib
import logging
import os
from typing import List, Optional, Dict, Any
import numpy as np
from pulse.ingestion.models import Review

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

logger = logging.getLogger(__name__)


def _get_review_hash(review: Review) -> str:
    """Generate SHA256 hash of review scrubbed text and rating."""
    payload = f"{review.text}|{review.rating}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def generate_embeddings(
    reviews: List[Review],
    model_name: str = "BAAI/bge-small-en-v1.5",
    batch_size: int = 64,
    cache_dir: Optional[str] = "data/cache/embeddings",
    min_reviews: int = 20,
) -> np.ndarray:
    """Generate numpy embeddings for scrubbed review texts with disk caching."""
    if len(reviews) < min_reviews:
        raise ValueError(f"Insufficient reviews for ML analysis: count={len(reviews)} < {min_reviews}.")

    hashes = [_get_review_hash(r) for r in reviews]
    cache: Dict[str, np.ndarray] = {}
    cache_file = None

    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        safe_model_name = model_name.replace("/", "_").replace("\\", "_")
        cache_file = os.path.join(cache_dir, f"cache_{safe_model_name}.npz")
        if os.path.exists(cache_file):
            try:
                with np.load(cache_file, allow_pickle=False) as data:
                    cache = {k: data[k] for k in data.files}
                logger.debug(f"Loaded {len(cache)} cached embeddings from {cache_file}.")
            except Exception as e:
                logger.warning(f"Failed to load embedding cache from {cache_file}: {e}")

    uncached_indices = [i for i, h in enumerate(hashes) if h not in cache]

    if uncached_indices:
        logger.info(f"Generating embeddings for {len(uncached_indices)} reviews using model {model_name}...")
        if SentenceTransformer is None:
            raise ImportError("sentence_transformers library is required for embedding generation.")

        model = SentenceTransformer(model_name)
        texts_to_encode = [reviews[i].text for i in uncached_indices]
        new_embeddings = model.encode(
            texts_to_encode,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

        for i, idx in enumerate(uncached_indices):
            cache[hashes[idx]] = new_embeddings[i]

        if cache_file:
            try:
                np.savez_compressed(cache_file, **cache)
                logger.debug(f"Saved {len(cache)} embeddings to cache file {cache_file}.")
            except Exception as e:
                logger.warning(f"Failed to save embedding cache to {cache_file}: {e}")
    else:
        logger.info(f"100% embedding cache hit ({len(reviews)} reviews).")

    embeddings = np.array([cache[h] for h in hashes])
    return embeddings
