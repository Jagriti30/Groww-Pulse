"""Unit tests for Phase 6 orchestrator and CLI commands."""

import json
import numpy as np
import pytest
from unittest.mock import MagicMock
from click.testing import CliRunner
from pulse.cli import cli
from pulse.agent.orchestrator import run_pulse
from pulse.ledger.store import LedgerStore


@pytest.fixture(autouse=True)
def mock_external_ml_and_llm(monkeypatch):
    # Mock Groq client
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps({
            "theme_name": "App performance & bugs",
            "summary": "Lag, crashes during trading hours; login/session timeouts.",
            "quotes": ["The app freezes exactly when the market opens every day."],
            "action_ideas": [{"title": "Scale infrastructure", "detail": "Increase server capacity at market open."}]
        })))
    ]
    mock_response.usage = MagicMock(total_tokens=150)
    mock_client.chat.completions.create.return_value = mock_response

    mock_groq_class = MagicMock(return_value=mock_client)
    monkeypatch.setattr("groq.Groq", mock_groq_class)

    # Mock SentenceTransformer
    def mock_st(*args, **kwargs):
        model = MagicMock()
        def fake_encode(texts, *a, **kw):
            return np.random.RandomState(42).rand(len(texts), 5)
        model.encode = fake_encode
        return model

    monkeypatch.setattr("pulse.pipeline.embeddings.SentenceTransformer", mock_st)


def test_orchestrator_dry_run(tmp_path):
    db_file = str(tmp_path / "test_run.db")
    res = run_pulse(product="groww", iso_week="2026-W23", dry_run=True, db_path=db_file)
    assert res["status"] == "dry_run"
    assert res["product"] == "groww"
    assert res["iso_week"] == "2026-W23"
    assert res["dry_run"] is True
    assert len(res["deliveries"]) == 0
    assert "doc_section_anchor" in res

    # Check that dry_run did not create a completed record in ledger
    store = LedgerStore(db_path=db_file)
    assert store.check_completed_run("groww", "2026-W23") is None


def test_cli_dry_run_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["dry-run", "--product", "groww", "--iso-week", "2026-W23"])
    assert result.exit_code == 0
    assert "Dry-run pipeline completed successfully" in result.output
    assert "2026-W23" in result.output


def test_cli_status_command(tmp_path, monkeypatch):
    # Setup temporary ledger
    db_file = str(tmp_path / "ledger.db")
    store = LedgerStore(db_path=db_file)
    store.init_db()
    
    # We monkeypatch the LedgerStore default constructor in cli.py to use our tmp db
    def mock_store(*args, **kwargs):
        return LedgerStore(db_path=db_file)
    
    monkeypatch.setattr("pulse.ledger.store.LedgerStore", mock_store)

    runner = CliRunner()
    # When empty
    res = runner.invoke(cli, ["status", "--product", "groww"])
    assert res.exit_code == 0
    assert "No ledger records found for product=groww" in res.output
