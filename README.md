# Weekly Product Review Pulse

An automated weekly "pulse" system that turns public Google Play Store reviews for selected fintech products (initially **Groww**) into a structured insight report, delivered to stakeholders through Google Workspace using **MCP (Model Context Protocol)** servers.

## Features
- **Play Store Ingestion:** Fetches, filters, and caches reviews over an 8–12 week rolling window.
- **ML & NLP Analysis:** Scrubs PII, filters scripts, embeds text locally with `sentence-transformers`, clusters with `UMAP + HDBSCAN`, and summarizes themes using Groq (`llama-3.3-70b-versatile`) with strict quote validation.
- **MCP Delivery:** Appends canonical weekly reports to Google Docs (`Google Docs MCP`) and sends stakeholder teasers via Gmail (`Gmail MCP`).
- **Audit & Idempotency:** Backed by a SQLite ledger and section anchor keys to prevent duplicate deliveries.

## Quickstart

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment:**
   Copy `.env.example` to `.env` and fill in your API keys:
   ```bash
   cp .env.example .env
   ```

3. **Run the CLI:**
   ```bash
   python -m pulse.cli --help
   ```

## Documentation
- [`problemStatement.md`](problemStatement.md) — Product intent and requirements.
- [`architecture.md`](architecture.md) — Technical design, data flows, and MCP integration.
- [`implementation-plan.md`](implementation-plan.md) — Phase-wise development roadmap.
