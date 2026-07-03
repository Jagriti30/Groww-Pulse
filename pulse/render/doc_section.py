"""Google Docs structured section builder (Phase 3)."""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import List
from pulse.ingestion.models import RunContext
from pulse.pipeline.quote_validator import PulseReport


@dataclass
class DocSection:
    anchor: str            # e.g. "groww-2026-W23"
    heading_text: str
    content: str           # Formatted text content ready for Docs MCP append


def _format_timestamp_ist(iso_ts: str) -> str:
    """Format ISO timestamp into 'YYYY-MM-DD IST' format."""
    ist = timezone(timedelta(hours=5, minutes=30))
    try:
        dt = datetime.fromisoformat(iso_ts)
        dt_ist = dt.astimezone(ist)
        return f"{dt_ist.strftime('%Y-%m-%d')} IST"
    except (ValueError, TypeError):
        if iso_ts and len(iso_ts) >= 10:
            return f"{iso_ts[:10]} IST"
        return "Unknown IST"


def build_doc_section(report: PulseReport, context: RunContext) -> DocSection:
    """Transform a PulseReport into formatted text content ready for Google Docs MCP append."""
    product_clean = context.product.lower()
    product_name = context.product.capitalize()
    iso_week = context.iso_week

    anchor = f"{product_clean}-{iso_week}"
    heading_text = f"{product_name} -- Weekly Review Pulse -- {iso_week}"

    gen_str = _format_timestamp_ist(report.generated_at)
    period_line = f"Period: Last {report.window_weeks} weeks (rolling) | Source: Google Play Store | Generated: {gen_str}"

    theme_items: List[str] = []
    quote_items: List[str] = []
    action_items: List[str] = []

    for theme in report.themes:
        theme_items.append(f"{theme.theme_name} -- {theme.summary}")
        for q in theme.quotes:
            q_clean = q.strip()
            if not q_clean.startswith('"'):
                q_clean = f'"{q_clean}"'
            quote_items.append(q_clean)
        for act in theme.action_ideas:
            action_items.append(f"{act.title} -- {act.detail}")

    who_items = [
        "Product -- Prioritize roadmap from recurring themes",
        "Support -- Spot repeating complaints and quality issues",
        "Leadership -- Fast health snapshot tied to customer voice",
    ]

    lines = [
        f"# {heading_text}",
        "",
        period_line,
        "",
        "---",
        "",
        "## Top themes",
        "",
    ]
    for item in theme_items:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Real user quotes")
    lines.append("")
    for item in quote_items:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Action ideas")
    lines.append("")
    for item in action_items:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Who this helps")
    lines.append("")
    for item in who_items:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("---")

    content = "\n".join(lines).strip()

    return DocSection(
        anchor=anchor,
        heading_text=heading_text,
        content=content,
    )
