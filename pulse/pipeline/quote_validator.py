"""Quote substring validation and report model definitions (Phase 2)."""

import logging
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Callable
from pulse.ingestion.models import Review

logger = logging.getLogger(__name__)


@dataclass
class ActionIdea:
    title: str
    detail: str


@dataclass
class Theme:
    theme_name: str
    summary: str
    quotes: List[str]          # Validated quotes only
    action_ideas: List[ActionIdea]
    cluster_size: int
    avg_rating: float


@dataclass
class PulseReport:
    product: str
    iso_week: str
    window_weeks: int
    review_count: int
    themes: List[Theme]
    generated_at: str          # ISO datetime


def _normalize_text(s: str) -> str:
    """Collapse whitespace and lowercase text for robust substring matching."""
    if not s:
        return ""
    return " ".join(s.strip().lower().split())


def _is_quote_valid(quote: str, target_reviews: List[Review]) -> bool:
    """Check if quote matches any target review text directly or via >=15 char ellipsis prefix."""
    norm_q = _normalize_text(quote)
    if not norm_q:
        return False

    # 1. Check exact substring match after normalization
    for r in target_reviews:
        if norm_q in _normalize_text(r.text):
            return True

    # 2. Check ellipsis truncation match (e.g. "The app freezes when...")
    parts = re.split(r'\.{2,}|\…', norm_q)
    prefix = parts[0].strip()
    if len(prefix) >= 15:
        for r in target_reviews:
            if prefix in _normalize_text(r.text):
                return True

    return False


def validate_quotes(
    raw_themes: List[Dict[str, Any]],
    reviews: List[Review],
    reprompt_fn: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None,
) -> List[Theme]:
    """Validate LLM-extracted quotes against scrubbed source reviews via substring matching."""
    validated_themes: List[Theme] = []

    for raw_theme in raw_themes:
        theme_name = raw_theme.get("theme_name", "Unnamed Theme")
        cluster_indices = raw_theme.get("review_indices", [])
        cluster_reviews = [reviews[idx] for idx in cluster_indices if idx < len(reviews)]

        valid_quotes: List[str] = []
        raw_quotes = raw_theme.get("quotes", [])
        if not isinstance(raw_quotes, list):
            raw_quotes = []

        for q in raw_quotes:
            if not isinstance(q, str) or not q.strip():
                continue
            # First check against same cluster
            if _is_quote_valid(q, cluster_reviews):
                valid_quotes.append(q)
            # Fallback to full scrubbed corpus
            elif _is_quote_valid(q, reviews):
                valid_quotes.append(q)
            else:
                logger.warning(f"Quote dropped (failed validation) in theme '{theme_name}': '{q}'")

        # If all quotes failed, optionally re-prompt
        if not valid_quotes and reprompt_fn is not None:
            logger.info(f"Theme '{theme_name}' lost all quotes. Attempting re-prompt...")
            try:
                new_theme = reprompt_fn(raw_theme)
                if new_theme and isinstance(new_theme.get("quotes"), list):
                    for q in new_theme["quotes"]:
                        if isinstance(q, str) and (_is_quote_valid(q, cluster_reviews) or _is_quote_valid(q, reviews)):
                            valid_quotes.append(q)
            except Exception as e:
                logger.error(f"Re-prompt failed for theme '{theme_name}': {e}")

        if not valid_quotes:
            logger.warning(f"Omitting theme '{theme_name}' because it has 0 validated quotes.")
            continue

        action_ideas = [
            ActionIdea(title=str(a.get("title", "")), detail=str(a.get("detail", "")))
            for a in raw_theme.get("action_ideas", [])
            if isinstance(a, dict)
        ]

        theme_obj = Theme(
            theme_name=str(theme_name),
            summary=str(raw_theme.get("summary", "")),
            quotes=valid_quotes,
            action_ideas=action_ideas,
            cluster_size=int(raw_theme.get("cluster_size", len(cluster_reviews))),
            avg_rating=float(raw_theme.get("avg_rating", 0.0)),
        )
        validated_themes.append(theme_obj)

    logger.info(f"Quote validation completed: {len(validated_themes)}/{len(raw_themes)} themes retained.")
    return validated_themes
