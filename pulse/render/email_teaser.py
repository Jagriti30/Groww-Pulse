"""Stakeholder email teaser builder (Phase 3)."""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from pulse.ingestion.models import RunContext
from pulse.pipeline.quote_validator import PulseReport


@dataclass
class EmailTeaser:
    subject: str
    html_body: str
    text_body: str
    recipients: List[str]
    idempotency_key: str   # e.g. "groww-2026-W23-email"


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


def build_email_teaser(
    report: PulseReport,
    context: RunContext,
    doc_url: str,
    recipients: Optional[List[str]] = None,
    heading_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> EmailTeaser:
    """Transform a PulseReport and target doc link into an HTML/text teaser email."""
    product_clean = context.product.lower()
    product_name = context.product.capitalize()
    iso_week = context.iso_week

    subject = f"{product_name} Weekly Review Pulse -- {iso_week}"
    idempotency_key = f"{product_clean}-{iso_week}-email"

    if recipients is None:
        if config and "delivery" in config and "email" in config["delivery"]:
            recipients = config["delivery"]["email"].get("recipients", [])
        else:
            recipients = ["stakeholders@example.com"]

    target_url = doc_url
    if heading_id and "#" not in target_url:
        target_url = f"{target_url}#heading={heading_id}"

    gen_str = _format_timestamp_ist(report.generated_at)

    theme_li_html_list = []
    theme_li_text_list = []
    for theme in report.themes[:5]:
        theme_li_html_list.append(
            f'<li style="margin-bottom: 8px;"><strong>{theme.theme_name}:</strong> {theme.summary}</li>'
        )
        theme_li_text_list.append(f"• {theme.theme_name} -- {theme.summary}")

    if not theme_li_html_list:
        theme_li_html_list.append("<li>No significant themes identified this week.</li>")
        theme_li_text_list.append("• No significant themes identified this week.")

    theme_li_html = "\n      ".join(theme_li_html_list)
    theme_li_text = "\n".join(theme_li_text_list)

    html_body = f"""<div style="font-family: Arial, sans-serif; max-width: 600px; color: #333; line-height: 1.5;">
  <h2 style="color: #1a73e8; margin-bottom: 10px;">{product_name} Weekly Review Pulse -- {iso_week}</h2>
  <p style="margin-bottom: 20px;">
    Here is a quick summary of the top customer feedback themes from <strong>{report.review_count}</strong> Google Play Store reviews analyzed over the rolling <strong>{report.window_weeks}-week</strong> window.
  </p>
  
  <h3 style="color: #202124; margin-bottom: 10px;">Top Themes</h3>
  <ul style="padding-left: 20px; margin-bottom: 25px;">
      {theme_li_html}
  </ul>
  
  <div style="margin: 25px 0;">
    <a href="{target_url}" style="background-color: #1a73e8; color: #ffffff; padding: 12px 20px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">Read Full Report &rarr;</a>
  </div>
  
  <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0 15px 0;" />
  <p style="font-size: 12px; color: #5f6368; margin: 0;">
    Generated at {gen_str} | Source: Google Play Store | <a href="{doc_url}" style="color: #5f6368;">Canonical Document</a>
  </p>
</div>"""

    text_body = f"""{product_name} Weekly Review Pulse -- {iso_week}

Here is a quick summary of the top customer feedback themes from {report.review_count} Google Play Store reviews analyzed over the rolling {report.window_weeks}-week window.

Top Themes:
{theme_li_text}

Read full report:
{target_url}

---
Generated at {gen_str} | Source: Google Play Store | Canonical Document: {doc_url}"""

    return EmailTeaser(
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        recipients=recipients,
        idempotency_key=idempotency_key,
    )
