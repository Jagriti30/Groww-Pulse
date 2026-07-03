"""FastAPI backend application for Weekly Product Review Pulse Control Tower (Phase 7)."""

import os
import json
import uuid
import yaml
import logging
import threading
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from pulse.agent.orchestrator import run_pulse
from pulse.ledger.store import LedgerStore
from pulse.ingestion.models import RunContext
from pulse.ingestion import fetch_and_cache_reviews
from pulse.pipeline.scrubber import scrub_pii
from pulse.pipeline.embeddings import generate_embeddings
from pulse.pipeline.clustering import cluster_reviews

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Weekly Product Review Pulse - Control Tower API",
    description="Interactive monitoring and orchestration engine for customer feedback ML pipelines.",
    version="1.0.0"
)

# Mount static frontend directory
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

# In-memory job store for async pipeline runs {job_id: {status, result, error}}
_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()


class RunRequest(BaseModel):
    product: str = "groww"
    iso_week: Optional[str] = None
    dry_run: bool = False
    email_mode: str = "draft"


@app.get("/")
def serve_index():
    """Serve the root Single Page Application (SPA)."""
    index_path = os.path.join(static_dir, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Frontend index.html not found.")
    return FileResponse(index_path)


@app.get("/api/status")
def get_status(product: str = "groww", iso_week: Optional[str] = None):
    """Retrieve historical audit ledger runs and their associated MCP deliveries."""
    try:
        store = LedgerStore()
        runs = store.get_runs(product, iso_week)
        result = []
        for r in runs:
            delivs = store.get_deliveries(r.run_id)
            report_data = None
            if r.report_json:
                try:
                    report_data = json.loads(r.report_json)
                except Exception:
                    report_data = None

            result.append({
                "run_id": r.run_id,
                "product": r.product,
                "iso_week": r.iso_week,
                "status": r.status,
                "review_count": r.review_count,
                "window_weeks": r.window_weeks,
                "started_at": r.started_at,
                "completed_at": r.completed_at,
                "error_message": r.error_message,
                "report": report_data,
                "deliveries": [
                    {
                        "channel": d.channel,
                        "external_id": d.external_id,
                        "url": d.url
                    }
                    for d in delivs
                ]
            })
        return {"status": "success", "runs": result}
    except Exception as e:
        logger.exception("Error fetching ledger status")
        raise HTTPException(status_code=500, detail=str(e))


def _run_pipeline_job(job_id: str, product: str, iso_week: Optional[str], dry_run: bool, email_mode: str):
    """Execute pipeline in a background thread and store result in job store."""
    try:
        logger.info(f"[Job {job_id}] Starting pipeline: product={product}, week={iso_week}, dry_run={dry_run}")
        result = run_pulse(product=product, iso_week=iso_week, dry_run=dry_run, email_mode=email_mode)
        with _jobs_lock:
            _jobs[job_id] = {"status": "completed", "result": result, "error": None}
        logger.info(f"[Job {job_id}] Pipeline completed successfully.")
    except Exception as e:
        logger.exception(f"[Job {job_id}] Pipeline failed: {e}")
        with _jobs_lock:
            _jobs[job_id] = {"status": "failed", "result": None, "error": str(e)}


@app.post("/api/run")
def trigger_run(req: RunRequest):
    """Kick off an async pipeline run and return a job_id for polling."""
    # Validate iso_week format to prevent malformed strings from crashing
    iso_week = req.iso_week
    if iso_week:
        iso_week = iso_week.strip()
        import re
        if not re.match(r'^\d{4}-W\d{2}$', iso_week):
            raise HTTPException(status_code=422, detail=f"Invalid iso_week format '{iso_week}'. Expected YYYY-Www (e.g. 2026-W27).")

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "result": None, "error": None}

    thread = threading.Thread(
        target=_run_pipeline_job,
        args=(job_id, req.product, iso_week, req.dry_run, req.email_mode),
        daemon=True,
    )
    thread.start()
    return {"status": "accepted", "job_id": job_id}


@app.get("/api/job/{job_id}")
def poll_job(job_id: str):
    """Poll the status of an async pipeline job."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    if job["status"] == "running":
        return {"status": "running", "job_id": job_id}
    elif job["status"] == "completed":
        return {"status": "success", "job_id": job_id, "result": job["result"]}
    else:
        return {"status": "error", "job_id": job_id, "detail": job["error"]}


@app.get("/api/clusters")
def get_clusters(product: str = "groww", iso_week: Optional[str] = None):
    """Compute 2D UMAP coordinates and HDBSCAN clusters for interactive scatter plot visualization."""
    try:
        import umap

        cfg_path = f"config/products/{product}.yaml"
        if not os.path.exists(cfg_path):
            raise HTTPException(status_code=404, detail=f"Product config not found: {product}")
        with open(cfg_path, "r", encoding="utf-8") as f:
            prod_cfg = yaml.safe_load(f)

        with open("config/pipeline.yaml", "r", encoding="utf-8") as f:
            pipe_cfg = yaml.safe_load(f)

        window_weeks = prod_cfg.get("ingestion", {}).get("window_weeks", 10)
        run_ctx = RunContext(product=product, iso_week=iso_week, window_weeks=window_weeks, dry_run=True, email_mode="draft")

        reviews = fetch_and_cache_reviews(prod_cfg, run_ctx)
        if not reviews:
            return {"status": "success", "points": [], "clusters": []}

        scrubbed = scrub_pii(reviews)

        if len(scrubbed) == 0:
            return {"status": "success", "points": [], "clusters": []}

        # Generate embeddings with relaxed floor for visualization
        embeddings = generate_embeddings(scrubbed, min_reviews=1)
        clusters = cluster_reviews(scrubbed, embeddings, pipe_cfg)

        # Reduce to 2D for interactive UI visualization
        if len(scrubbed) >= 5:
            n_neighbors = min(15, len(scrubbed) - 1)
            reducer_2d = umap.UMAP(n_components=2, n_neighbors=n_neighbors, random_state=42)
            coords_2d = reducer_2d.fit_transform(embeddings)
        else:
            # Fallback for tiny test sets
            coords_2d = [[float(i), float(i)] for i in range(len(scrubbed))]

        idx_to_cluster = {}
        for c in clusters:
            cid = c["cluster_id"]
            avg_r = c.get("avg_rating", 0.0)
            size = c.get("cluster_size", 0)
            # dominant_topic is only available post-summarization; use descriptive fallback
            cname = c.get("dominant_topic") or f"Cluster {cid} ({size} reviews, ⭐{avg_r:.1f})"
            for idx in c.get("review_indices", []):
                idx_to_cluster[idx] = (cid, cname)

        points = []
        for i, rev in enumerate(scrubbed):
            cid, cname = idx_to_cluster.get(i, (-1, "Noise / Unclustered"))
            points.append({
                "index": i,
                "x": float(coords_2d[i][0]),
                "y": float(coords_2d[i][1]),
                "text": rev.text[:150] + ("..." if len(rev.text) > 150 else ""),
                "full_text": rev.text,
                "rating": rev.rating,
                "cluster_id": cid,
                "cluster_name": cname
            })

        return {"status": "success", "points": points, "clusters": clusters}
    except Exception as e:
        logger.exception("Error computing 2D clusters")
        raise HTTPException(status_code=500, detail=str(e))
