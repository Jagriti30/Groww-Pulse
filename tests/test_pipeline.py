"""Unit tests for Phase 2 (Analysis Pipeline: scrubbing, embedding, clustering, summarization, quote validation)."""

import json
from unittest.mock import MagicMock, patch
import numpy as np
import pytest
from pulse.ingestion.models import Review, RunContext
from pulse.pipeline import (
    is_latin_dominant,
    filter_scripts,
    scrub_pii,
    generate_embeddings,
    cluster_reviews,
    stratified_sample,
    summarize_clusters,
    validate_quotes,
    run_pipeline,
    PulseReport,
)


def test_script_filter():
    reviews = [
        Review(text="Bahut accha app hai bhai, maza aa gaya invest karke!", rating=5),  # Hinglish (100% ASCII)
        Review(text="Good app for mutual fund investment.", rating=4),                   # English
        Review(text="यह एक बहुत अच्छा ऐप है शेयर बाजार के लिए", rating=5),                # Devanagari (<80% ASCII)
        Review(text="Nice UI 🌟", rating=4),                                             # English + Emoji (high ASCII ratio)
    ]
    filtered = filter_scripts(reviews, min_ascii_ratio=0.80)
    assert len(filtered) == 3
    assert not any("यह" in r.text for r in filtered)
    assert any("Bahut accha" in r.text for r in filtered)


def test_pii_scrubber():
    reviews = [
        Review(
            text="Please contact me at test.user+groww@example.co.in or call +91 9876543210 regarding my issue.",
            rating=1,
        ),
        Review(
            text="My PAN is ABCDE1234F and Aadhaar is 1234-5678-9012. Fix my account!",
            rating=1,
        ),
        Review(
            text="Check screenshot at https://groww.in/help/support?token=secret123 immediately.",
            rating=2,
        ),
        Review(
            text="I invested ₹10,000 and Rs 50000 but withdrawal of 100000 rupees failed.",
            rating=1,
        ),
    ]

    scrubbed = scrub_pii(reviews)

    # 1. Email and phone redacted
    assert "[EMAIL]" in scrubbed[0].text
    assert "[PHONE]" in scrubbed[0].text
    assert "test.user" not in scrubbed[0].text
    assert "9876543210" not in scrubbed[0].text

    # 2. PAN and Aadhaar redacted
    assert "[ID]" in scrubbed[1].text
    assert "ABCDE1234F" not in scrubbed[1].text
    assert "1234-5678-9012" not in scrubbed[1].text

    # 3. URL path/token redacted
    assert "https://groww.in/[URL]" in scrubbed[2].text
    assert "secret123" not in scrubbed[2].text

    # 4. Financial amounts kept
    assert "₹10,000" in scrubbed[3].text
    assert "50000" in scrubbed[3].text
    assert "100000 rupees" in scrubbed[3].text


def test_embeddings_ml_floor():
    small_reviews = [Review(text=f"Review number {i}", rating=5) for i in range(15)]
    with pytest.raises(ValueError, match="Insufficient reviews for ML analysis"):
        generate_embeddings(small_reviews)


@patch("pulse.pipeline.embeddings.SentenceTransformer")
def test_embeddings_caching(mock_st_class, tmp_path):
    cache_dir = str(tmp_path)
    mock_model = MagicMock()
    # Return dummy 3-dim embeddings
    mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]] * 20)
    mock_st_class.return_value = mock_model

    reviews = [Review(text=f"Review text number {i} for investing.", rating=4) for i in range(20)]

    # First run: should call encode
    emb1 = generate_embeddings(reviews, model_name="test/model", cache_dir=cache_dir)
    assert emb1.shape == (20, 3)
    mock_model.encode.assert_called_once()

    # Second run: should hit cache and NOT call encode again
    mock_model.encode.reset_mock()
    emb2 = generate_embeddings(reviews, model_name="test/model", cache_dir=cache_dir)
    assert emb2.shape == (20, 3)
    mock_model.encode.assert_not_called()
    np.testing.assert_array_equal(emb1, emb2)


def test_clustering_fallback_and_dominant_split():
    # 25 reviews total
    reviews = [Review(text=f"Complaint review {i}", rating=1) for i in range(20)] + \
              [Review(text=f"Good review {i}", rating=5) for i in range(5)]
    # Dummy embeddings
    embeddings = np.random.RandomState(42).rand(25, 5)

    config = {
        "clustering": {"hdbscan": {"min_cluster_size": 3, "min_samples": 2}},
        "summarization": {"max_themes": 5},
    }

    # Even with random embeddings, cluster_reviews should run without error
    # and return structured cluster dictionaries
    clusters = cluster_reviews(reviews, embeddings, config)
    assert isinstance(clusters, list)
    for c in clusters:
        assert "cluster_id" in c
        assert "review_indices" in c
        assert "score" in c


def test_stratified_sample():
    reviews = [Review(text=f"1 star {i}", rating=1) for i in range(16)] + \
              [Review(text=f"5 star {i}", rating=5) for i in range(4)]
    samples = stratified_sample(reviews, n=10)
    assert len(samples) <= 10
    ratings = [r.rating for r in samples]
    # Should proportionally sample more 1-star reviews than 5-star reviews
    assert ratings.count(1) > ratings.count(5)


def test_summarizer_with_mock():
    reviews = [
        Review(text="The app freezes during market opening hours.", rating=1),
        Review(text="Unable to withdraw money to bank account.", rating=2),
    ]
    clusters = [
        {"cluster_id": "0", "review_indices": [0, 1], "cluster_size": 2, "avg_rating": 1.5, "score": 9.0}
    ]

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps({
            "theme_name": "App Freezing & Withdrawals",
            "summary": "Users experience app freezing at market open and withdrawal issues.",
            "quotes": ["The app freezes during market opening hours."],
            "action_ideas": [{"title": "Fix server capacity", "detail": "Scale servers at 9:15 AM."}]
        })))
    ]
    mock_response.usage = MagicMock(total_tokens=150)
    mock_client.chat.completions.create.return_value = mock_response

    summaries = summarize_clusters(clusters, reviews, client=mock_client)
    assert len(summaries) == 1
    assert summaries[0]["theme_name"] == "App Freezing & Withdrawals"
    assert summaries[0]["quotes"] == ["The app freezes during market opening hours."]
    assert len(summaries[0]["action_ideas"]) == 1


def test_quote_validator_substring_and_ellipsis():
    reviews = [
        Review(text="The app freezes exactly when the market opens every day.", rating=1),
        Review(text="Very nice application for trading stocks.", rating=5),
    ]

    raw_themes = [
        {
            "theme_name": "Freezing Issues",
            "summary": "App freezes at market open.",
            "quotes": [
                # 1. Exact substring match
                "The app freezes exactly when the market opens every day.",
                # 2. Valid ellipsis truncation (prefix >= 15 chars: "The app freezes exactly when the")
                "The app freezes exactly when the...",
                # 3. Invalid ellipsis truncation (prefix < 15 chars: "The app...")
                "The app...",
                # 4. Completely hallucinated quote
                "This quote does not exist anywhere in the reviews.",
            ],
            "action_ideas": [{"title": "Fix bugs", "detail": "Optimize code."}],
            "review_indices": [0],
            "cluster_size": 1,
            "avg_rating": 1.0,
        },
        {
            "theme_name": "Dropped Theme",
            "summary": "This theme has only hallucinated quotes.",
            "quotes": ["Hallucinated quote 1", "Hallucinated quote 2"],
            "action_ideas": [],
            "review_indices": [1],
            "cluster_size": 1,
            "avg_rating": 5.0,
        }
    ]

    validated = validate_quotes(raw_themes, reviews)

    # The second theme should be omitted because all quotes were dropped!
    assert len(validated) == 1
    theme = validated[0]
    assert theme.theme_name == "Freezing Issues"
    # Only exact match and valid ellipsis match should survive
    assert len(theme.quotes) == 2
    assert "The app freezes exactly when the market opens every day." in theme.quotes
    assert "The app freezes exactly when the..." in theme.quotes
    assert "The app..." not in theme.quotes


@patch("pulse.pipeline.embeddings.SentenceTransformer")
def test_run_pipeline_end_to_end(mock_st_class, tmp_path):
    mock_model = MagicMock()
    # Dummy 5-dim embeddings for 20 reviews
    mock_model.encode.return_value = np.random.RandomState(42).rand(20, 5)
    mock_st_class.return_value = mock_model

    reviews = [
        Review(text=f"The application crashes when trading stock number {i} in market.", rating=1 if i < 15 else 5)
        for i in range(20)
    ]

    config = {
        "embedding": {"model": "test-model", "batch_size": 32},
        "clustering": {"hdbscan": {"min_cluster_size": 3, "min_samples": 2}},
        "summarization": {"max_themes": 3, "request_interval_seconds": 0.0},
    }
    run_ctx = RunContext(product="groww", iso_week="2026-W23", window_weeks=10, dry_run=True, email_mode="draft")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps({
            "theme_name": "Trading Crashes",
            "summary": "Frequent crashes reported during trading.",
            "quotes": ["The application crashes when trading stock number 0 in market."],
            "action_ideas": [{"title": "Investigate crash logs", "detail": "Check null pointer exceptions."}]
        })))
    ]
    mock_response.usage = MagicMock(total_tokens=200)
    mock_client.chat.completions.create.return_value = mock_response

    report = run_pipeline(reviews, config, run_ctx, client=mock_client)

    assert isinstance(report, PulseReport)
    assert report.product == "groww"
    assert report.review_count == 20
    assert len(report.themes) > 0
    assert report.themes[0].theme_name == "Trading Crashes"
    assert len(report.themes[0].quotes) == 1
