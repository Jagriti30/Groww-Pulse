"""Automated tests for FastAPI Web Dashboard & Control Tower (Phase 7)."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from pulse.web.api import app

client = TestClient(app)


def test_serve_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "GROWW PULSE" in response.text
    assert "AI CONTROL TOWER" in response.text


def test_serve_static_css():
    response = client.get("/static/styles.css")
    assert response.status_code == 200
    assert "--bg-main" in response.text


def test_serve_static_js():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    assert "initApp()" in response.text


def test_get_status():
    response = client.get("/api/status?product=groww")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "runs" in data
    assert isinstance(data["runs"], list)


@patch("pulse.web.api.fetch_and_cache_reviews")
@patch("pulse.web.api.generate_embeddings")
@patch("pulse.web.api.cluster_reviews")
def test_get_clusters(mock_cluster, mock_embed, mock_fetch):
    from pulse.ingestion.models import Review
    import numpy as np

    # Mock 3 English reviews
    mock_reviews = [
        Review(text="App crash during trading hours", rating=1),
        Review(text="Great UI experience", rating=5),
        Review(text="Slow login process", rating=2)
    ]
    mock_fetch.return_value = mock_reviews
    mock_embed.return_value = np.zeros((3, 5))
    mock_cluster.return_value = [
        {"cluster_id": 0, "dominant_topic": "Crashes & Speed", "review_indices": [0, 2]},
        {"cluster_id": 1, "dominant_topic": "UI Experience", "review_indices": [1]}
    ]

    response = client.get("/api/clusters?product=groww")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["points"]) == 3
    assert data["points"][0]["cluster_name"] == "Crashes & Speed"
    assert data["points"][1]["cluster_name"] == "UI Experience"


@patch("pulse.web.api.run_pulse")
def test_trigger_run_endpoint(mock_run):
    mock_run.return_value = {
        "run_id": "test-run-id-123",
        "product": "groww",
        "iso_week": "2026-W27",
        "status": "dry_run",
        "dry_run": True
    }

    response = client.post("/api/run", json={
        "product": "groww",
        "iso_week": "2026-W27",
        "dry_run": True,
        "email_mode": "draft"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert "job_id" in data

    import time
    job_id = data["job_id"]
    # Poll until completed
    for _ in range(20):
        res = client.get(f"/api/job/{job_id}")
        assert res.status_code == 200
        job_data = res.json()
        if job_data["status"] == "success":
            assert job_data["result"]["run_id"] == "test-run-id-123"
            assert job_data["result"]["dry_run"] is True
            break
        time.sleep(0.05)
    else:
        assert False, "Job did not complete in time"
