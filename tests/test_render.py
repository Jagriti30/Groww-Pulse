"""Unit tests for Phase 3 (Output Generation: Google Doc section builder and Gmail teaser builder)."""

import pytest
from pulse.ingestion.models import RunContext
from pulse.pipeline.quote_validator import ActionIdea, Theme, PulseReport
from pulse.render import build_doc_section, build_email_teaser, DocSection, EmailTeaser


@pytest.fixture
def sample_report():
    themes = [
        Theme(
            theme_name="App performance & bugs",
            summary="Lag, crashes during trading hours; login/session timeouts.",
            quotes=[
                "The app freezes exactly when the market opens, very frustrating.",
                "Session logged out automatically during peak trading.",
            ],
            action_ideas=[
                ActionIdea(
                    title="Stabilize peak-time performance",
                    detail="Scale infra during market hours; improve crash visibility.",
                )
            ],
            cluster_size=120,
            avg_rating=1.4,
        ),
        Theme(
            theme_name="Customer support friction",
            summary="Slow responses; unresolved tickets.",
            quotes=[
                "Support takes days to reply and doesn't solve the issue.",
            ],
            action_ideas=[
                ActionIdea(
                    title="Improve support SLA visibility",
                    detail="Expected response time in-app; ticket status tracking.",
                )
            ],
            cluster_size=80,
            avg_rating=1.8,
        ),
        Theme(
            theme_name="UX & feature gaps",
            summary="Confusing navigation for portfolio insights; missing advanced analytics.",
            quotes=[
                "Good for beginners but lacks detailed analysis tools.",
            ],
            action_ideas=[
                ActionIdea(
                    title="Enhance power-user features",
                    detail="Advanced portfolio analytics; clearer investments navigation.",
                )
            ],
            cluster_size=50,
            avg_rating=2.5,
        ),
    ]

    return PulseReport(
        product="groww",
        iso_week="2026-W23",
        window_weeks=10,
        review_count=1250,
        themes=themes,
        generated_at="2026-06-08T10:30:00Z",
    )


@pytest.fixture
def sample_context():
    return RunContext(
        product="groww",
        iso_week="2026-W23",
        window_weeks=10,
        dry_run=False,
        email_mode="draft",
    )


def test_build_doc_section(sample_report, sample_context):
    doc_sec = build_doc_section(sample_report, sample_context)

    assert isinstance(doc_sec, DocSection)
    # Check anchor and heading text conventions
    assert doc_sec.anchor == "groww-2026-W23"
    assert doc_sec.heading_text == "Groww -- Weekly Review Pulse -- 2026-W23"

    # Check formatted text content
    assert "# Groww -- Weekly Review Pulse -- 2026-W23" in doc_sec.content
    assert "Period: Last 10 weeks (rolling)" in doc_sec.content
    assert "2026-06-08 IST" in doc_sec.content
    assert "## Top themes" in doc_sec.content
    assert "## Real user quotes" in doc_sec.content
    assert "## Action ideas" in doc_sec.content
    assert "## Who this helps" in doc_sec.content
    assert "- App performance & bugs -- Lag, crashes during trading hours;" in doc_sec.content
    assert '- "The app freezes exactly when the market opens, very frustrating."' in doc_sec.content
    assert "- Stabilize peak-time performance -- Scale infra during market hours;" in doc_sec.content
    assert "- Product -- Prioritize roadmap from recurring themes" in doc_sec.content


def test_build_email_teaser(sample_report, sample_context):
    doc_url = "https://docs.google.com/document/d/12345ABC"
    teaser = build_email_teaser(sample_report, sample_context, doc_url, heading_id="h.abc123xyz")

    assert isinstance(teaser, EmailTeaser)
    # Check conventions
    assert teaser.subject == "Groww Weekly Review Pulse -- 2026-W23"
    assert teaser.idempotency_key == "groww-2026-W23-email"

    # Check target URL formatting with heading fragment
    expected_link = "https://docs.google.com/document/d/12345ABC#heading=h.abc123xyz"
    assert expected_link in teaser.html_body
    assert expected_link in teaser.text_body

    # Check content in HTML body
    assert "Groww Weekly Review Pulse -- 2026-W23" in teaser.html_body
    assert "1250" in teaser.html_body
    assert "10-week" in teaser.html_body
    assert "App performance & bugs:" in teaser.html_body
    assert "Customer support friction:" in teaser.html_body
    assert "UX & feature gaps:" in teaser.html_body
    assert "Read Full Report" in teaser.html_body
    assert "2026-06-08 IST" in teaser.html_body

    # Check content in plain text body
    assert "Groww Weekly Review Pulse -- 2026-W23" in teaser.text_body
    assert "• App performance & bugs -- Lag, crashes during trading hours;" in teaser.text_body
    assert expected_link in teaser.text_body


def test_build_email_teaser_with_config(sample_report, sample_context):
    config = {
        "delivery": {
            "email": {
                "recipients": ["execs@groww.in", "support@groww.in"]
            }
        }
    }
    teaser = build_email_teaser(
        sample_report,
        sample_context,
        "https://docs.google.com/document/d/doc123",
        config=config,
    )
    assert teaser.recipients == ["execs@groww.in", "support@groww.in"]
    assert "https://docs.google.com/document/d/doc123" in teaser.html_body
