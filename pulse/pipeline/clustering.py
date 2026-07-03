"""UMAP and HDBSCAN review clustering module (Phase 2)."""

import logging
from typing import List, Dict, Any
import numpy as np
from pulse.ingestion.models import Review

logger = logging.getLogger(__name__)


def cluster_reviews(reviews: List[Review], embeddings: Any, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Cluster review embeddings using UMAP + HDBSCAN and rank top complaint clusters."""
    if not reviews or embeddings is None or len(reviews) == 0:
        return []

    try:
        import umap
        import hdbscan
    except ImportError as e:
        raise ImportError("umap-learn and hdbscan packages are required for clustering.") from e

    clustering_cfg = config.get("clustering", {})
    umap_cfg = clustering_cfg.get("umap", {})
    n_neighbors = umap_cfg.get("n_neighbors", 15)
    n_components = umap_cfg.get("n_components", 5)
    metric = umap_cfg.get("metric", "cosine")
    random_state = umap_cfg.get("random_state", 42)

    hdbscan_cfg = clustering_cfg.get("hdbscan", {})
    min_cluster_size = hdbscan_cfg.get("min_cluster_size", 5)
    min_samples = hdbscan_cfg.get("min_samples", 3)

    max_themes = config.get("summarization", {}).get("max_themes", 5)

    n_reviews = len(reviews)
    adj_neighbors = max(2, min(n_neighbors, n_reviews - 1))
    adj_components = max(2, min(n_components, n_reviews - 1))

    logger.info(f"Running UMAP (neighbors={adj_neighbors}, components={adj_components})...")
    reducer = umap.UMAP(
        n_neighbors=adj_neighbors,
        n_components=adj_components,
        metric=metric,
        random_state=random_state,
    )
    reduced_embeddings = reducer.fit_transform(embeddings)

    logger.info(f"Running HDBSCAN (min_cluster_size={min_cluster_size}, min_samples={min_samples})...")
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
    )
    labels = clusterer.fit_predict(reduced_embeddings)

    unique_labels = set(labels) - {-1}
    # Fallback 1: All noise -> lower min_cluster_size
    if not unique_labels and min_cluster_size > 2:
        new_mcs = max(2, min_cluster_size // 2)
        new_ms = max(1, min_samples // 2)
        logger.warning(f"All noise detected in HDBSCAN. Lowering min_cluster_size from {min_cluster_size} to {new_mcs}.")
        clusterer = hdbscan.HDBSCAN(min_cluster_size=new_mcs, min_samples=new_ms)
        labels = clusterer.fit_predict(reduced_embeddings)
        unique_labels = set(labels) - {-1}

    # If still all noise, put all reviews in a single fallback cluster
    if not unique_labels:
        logger.warning("All reviews clustered as noise. Creating a single fallback cluster (id=0).")
        labels = np.zeros(n_reviews, dtype=int)

    clusters_map: Dict[int, List[int]] = {}
    for idx, label in enumerate(labels):
        if label != -1:
            clusters_map.setdefault(label, []).append(idx)

    # Fallback 2: One cluster > 60% of corpus -> rating split
    final_clusters_map: Dict[str, List[int]] = {}
    cluster_counter = 0
    for label, indices in clusters_map.items():
        if len(indices) > 0.60 * n_reviews and len(indices) >= 4:
            logger.info(f"Cluster {label} has {len(indices)} reviews (>60% of corpus). Performing mandatory rating split.")
            low_stars = [i for i in indices if reviews[i].rating <= 2]
            mid_stars = [i for i in indices if reviews[i].rating == 3]
            high_stars = [i for i in indices if reviews[i].rating >= 4]

            if low_stars:
                final_clusters_map[str(cluster_counter)] = low_stars
                cluster_counter += 1
            if mid_stars:
                final_clusters_map[str(cluster_counter)] = mid_stars
                cluster_counter += 1
            if high_stars:
                final_clusters_map[str(cluster_counter)] = high_stars
                cluster_counter += 1
        else:
            final_clusters_map[str(cluster_counter)] = indices
            cluster_counter += 1

    cluster_list = []
    for cid, indices in final_clusters_map.items():
        if not indices:
            continue
        size = len(indices)
        avg_rating = sum(reviews[i].rating for i in indices) / size
        # Score = size * (6 - avg_rating) -> prioritizes large complaint clusters
        score = size * (6.0 - avg_rating)
        cluster_list.append({
            "cluster_id": cid,
            "review_indices": indices,
            "cluster_size": size,
            "avg_rating": round(avg_rating, 2),
            "score": round(score, 2),
        })

    cluster_list.sort(key=lambda x: x["score"], reverse=True)
    top_clusters = cluster_list[:max_themes]

    logger.info(f"Clustering completed: selected top {len(top_clusters)} clusters from {len(cluster_list)} valid clusters.")
    return top_clusters
