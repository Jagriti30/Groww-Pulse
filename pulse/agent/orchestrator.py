"""End-to-end pulse run coordinator (Phase 6)."""

import os
import json
import uuid
import yaml
import logging
from datetime import datetime, timezone
from dataclasses import asdict
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

load_dotenv()

from pulse.ingestion.models import RunContext
from pulse.ingestion import fetch_and_cache_reviews
from pulse.pipeline import run_pipeline
from pulse.render import build_doc_section, build_email_teaser
from pulse.agent.mcp_client import MCPClient
from pulse.ledger.models import RunRecord, DeliveryRecord
from pulse.ledger.store import LedgerStore

logger = logging.getLogger(__name__)


def load_yaml_config(path: str) -> Dict[str, Any]:
    """Helper to safely load YAML files or return empty dictionary if missing."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def run_pulse(
    product: str,
    iso_week: Optional[str] = None,
    dry_run: bool = False,
    email_mode: str = "draft",
    db_path: str = "data/ledger.db",
) -> Dict[str, Any]:
    """Orchestrate the review ingestion, ML analysis, rendering, and MCP delivery pipeline."""
    now = datetime.now(timezone.utc)
    if not iso_week:
        year, week, _ = now.isocalendar()
        iso_week = f"{year}-W{week:02d}"

    logger.info(f"Starting pulse orchestrator for product={product}, week={iso_week}, dry_run={dry_run}, mode={email_mode}")

    # 1. Load configurations
    product_config = load_yaml_config(f"config/products/{product}.yaml")
    pipeline_config = load_yaml_config("config/pipeline.yaml")

    ingestion_cfg = product_config.get("ingestion", {})
    pipeline_config["ingestion"] = ingestion_cfg
    window_weeks = ingestion_cfg.get("window_weeks", 10)

    run_context = RunContext(
        product=product,
        iso_week=iso_week,
        window_weeks=window_weeks,
        dry_run=dry_run,
        email_mode=email_mode,
    )

    # 2. Check ledger idempotency
    store = LedgerStore(db_path=db_path)
    completed_run = store.check_completed_run(product, iso_week)
    if completed_run and not dry_run:
        logger.info(f"Run for {product} ({iso_week}) already completed (run_id={completed_run.run_id}). Returning no-op.")
        return {
            "status": "already_completed",
            "run_id": completed_run.run_id,
            "product": product,
            "iso_week": iso_week,
            "review_count": completed_run.review_count,
            "message": "An idempotent run has already completed for this product and week.",
            "deliveries": [asdict(d) for d in store.get_deliveries(completed_run.run_id)],
        }

    # 3. Initialize run record
    run_id = str(uuid.uuid4())
    started_at = now.isoformat()
    run = RunRecord(
        run_id=run_id,
        product=product,
        iso_week=iso_week,
        status="pending",
        review_count=0,
        window_weeks=window_weeks,
        started_at=started_at,
    )

    # 4. Ingestion
    try:
        logger.info("Executing Step 1: Ingestion...")
        reviews = fetch_and_cache_reviews(product_config, run_context)
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc).isoformat()
        run.error_message = f"Ingestion failed: {e}"
        if not dry_run:
            store.record_run(run, [])
        raise

    # 5. ML Pipeline Analysis
    try:
        logger.info("Executing Step 2: Analysis Pipeline...")
        report = run_pipeline(reviews, pipeline_config, run_context)
    except Exception as e:
        logger.error(f"Analysis pipeline failed: {e}")
        run.status = "failed"
        run.review_count = len(reviews) if reviews else 0
        run.completed_at = datetime.now(timezone.utc).isoformat()
        run.error_message = f"Pipeline analysis failed: {e}"
        if not dry_run:
            store.record_run(run, [])
        raise

    run.review_count = report.review_count
    run.report_json = json.dumps(asdict(report), default=str)

    # Optional: Save report snapshot
    try:
        snapshot_dir = f"data/runs/{run_id}"
        os.makedirs(snapshot_dir, exist_ok=True)
        with open(f"{snapshot_dir}/report.json", "w", encoding="utf-8") as f:
            f.write(run.report_json)
    except Exception as e:
        logger.warning(f"Could not save report snapshot to disk: {e}")

    # 6. Render
    logger.info("Executing Step 3: Rendering artifacts...")
    section = build_doc_section(report, run_context)

    # Determine canonical Doc ID and URL
    doc_id = os.environ.get("GOOGLE_DOC_ID")
    if not doc_id:
        doc_id = product_config.get("delivery", {}).get("google_doc_id", "1n-S9qT-R_YaBhQi07o7lRYurF9ulzUX5Iz1pGOITIRU")
    doc_id = MCPClient._sanitize_doc_id(doc_id)
    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

    teaser = build_email_teaser(report, run_context, doc_url, config=product_config)

    if dry_run:
        logger.info("Dry run requested. Skipping MCP writes and ledger completion record.")
        return {
            "status": "dry_run",
            "run_id": run_id,
            "product": product,
            "iso_week": iso_week,
            "review_count": run.review_count,
            "dry_run": True,
            "deliveries": [],
            "doc_section_anchor": section.anchor,
            "email_subject": teaser.subject,
        }

    # 7. Deliver via MCP
    deliveries: List[DeliveryRecord] = []
    server_url = os.environ.get("MCP_SERVER_URL", "https://web-production-af4fc.up.railway.app")
    api_key = os.environ.get("MCP_API_KEY")
    client = MCPClient(server_url=server_url, api_key=api_key)

    # 7a. Google Docs MCP Delivery
    logger.info("Executing Step 4: Google Docs MCP Delivery...")
    try:
        doc_res = client.append_section(doc_id=doc_id, anchor=section.anchor, content=section.content)
        final_doc_url = doc_res.get("docUrl") or doc_url
        deliveries.append(
            DeliveryRecord(
                run_id=run_id,
                channel="google_doc",
                external_id=str(doc_res.get("headingId") or section.anchor),
                url=final_doc_url,
                idempotency_key=section.anchor,
            )
        )
    except Exception as e:
        logger.error(f"Google Docs delivery failed: {e}")
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc).isoformat()
        run.error_message = f"Google Docs delivery failed: {e}"
        store.record_run(run, deliveries)
        raise

    # Re-render email teaser if a specific heading_id was returned by Doc delivery
    heading_id = None
    for d in deliveries:
        if d.channel == "google_doc" and d.external_id != section.anchor:
            heading_id = d.external_id
    if heading_id:
        teaser = build_email_teaser(report, run_context, doc_url, heading_id=heading_id, config=product_config)

    # 7b. Gmail MCP Delivery
    logger.info("Executing Step 5: Gmail MCP Delivery...")
    try:
        if email_mode.lower() == "send":
            email_res = client.send_email(
                to=teaser.recipients,
                subject=teaser.subject,
                body=teaser.text_body,
                html_body=teaser.html_body,
                text_body=teaser.text_body,
            )
        else:
            email_res = client.create_email_draft(
                to=teaser.recipients,
                subject=teaser.subject,
                body=teaser.text_body,
                html_body=teaser.html_body,
                text_body=teaser.text_body,
            )

        external_id = (
            email_res.get("draftId")
            or email_res.get("draft_id")
            or email_res.get("messageId")
            or email_res.get("message_id")
            or teaser.idempotency_key
        )
        deliveries.append(
            DeliveryRecord(
                run_id=run_id,
                channel="gmail",
                external_id=str(external_id),
                url=f"https://mail.google.com/mail/u/0/#drafts/{external_id}" if "draft" in email_mode.lower() else "sent",
                idempotency_key=teaser.idempotency_key,
            )
        )
    except Exception as e:
        logger.error(f"Gmail delivery failed: {e}")
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc).isoformat()
        run.error_message = f"Gmail delivery failed: {e}"
        store.record_run(run, deliveries)
        raise

    # All steps successful!
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc).isoformat()
    store.record_run(run, deliveries)
    logger.info(f"Pulse run completed successfully for {product} ({iso_week}). Run ID: {run_id}")

    return {
        "status": run.status,
        "run_id": run_id,
        "product": product,
        "iso_week": iso_week,
        "review_count": run.review_count,
        "dry_run": False,
        "deliveries": [asdict(d) for d in deliveries],
    }
