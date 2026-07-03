# Weekly Product Review Pulse — Comprehensive Edge & Corner Cases

This document enumerates all known architectural, data, algorithmic, integration, and operational edge cases across the **Weekly Product Review Pulse** project. It serves as a testing checklist, defensive engineering guide, and operational runbook for developers and DevOps engineers.

---

## Table of Contents
1. [Phase 1 — Ingestion & Data Storage](#1-phase-1--ingestion--data-storage)
2. [Phase 2 — Clustering & LLM Summarization](#2-phase-2--clustering--llm-summarization)
3. [Phase 3 — Quote Verification & Rendering](#3-phase-3--quote-verification--rendering)
4. [Phase 4 — Google Docs MCP Delivery](#4-phase-4--google-docs-mcp-delivery)
5. [Phase 5 — Gmail MCP Delivery](#5-phase-5--gmail-mcp-delivery)
6. [Phase 6 — Orchestration, CLI & Audit Ledger](#6-phase-6--orchestration-cli--audit-ledger)
7. [Cross-Cutting Concerns](#7-cross-cutting-concerns)

---

## 1. Phase 1 — Ingestion & Data Storage

### 1.1 Data Scarcity & Zero-Review Windows
- **Edge Case**: A product (e.g., a newly launched B2B app or niche tool) receives `0` or `< 5` reviews within the configured rolling window (e.g., 10 weeks).
- **Impact**: Clustering algorithms (like HDBSCAN or UMAP) fail due to insufficient sample sizes ($N < \text{min\_samples}$).
- **Mitigation / Behavior**: The ingestion layer must detect low review volumes and flag the run context. If $0$ reviews are found, the pipeline should short-circuit with a clean `"No new reviews analyzed"` status without invoking LLM or clustering APIs. If $0 < N < \text{min\_samples}$, bypass clustering and feed all reviews directly into a single fallback cluster for LLM summarization.

### 1.2 Upstream Scraper & API Throttling
- **Edge Case**: The app store review scraper (e.g., Google Play Store API / web scraper) experiences HTTP `429 Too Many Requests`, HTTP `403 Forbidden`, or network connection dropouts during ingestion.
- **Impact**: Incomplete review datasets or pipeline crash.
- **Mitigation / Behavior**: Implement exponential backoff with jitter on scraping requests. Cache ingested reviews in local SQLite DB (`reviews` table) immediately upon retrieval so subsequent re-runs do not re-scrape external APIs.

### 1.3 Malformed, Null, & Non-Standard Data Fields
- **Edge Case**: Reviews contain `NULL` author names, empty string text bodies, out-of-range star ratings (e.g., `0` or `6`), or corrupted ISO timestamps.
- **Impact**: Database schema validation errors or downstream string manipulation crashes.
- **Mitigation / Behavior**: Ensure SQLite schema enforces standard defaults (`author DEFAULT 'Anonymous'`, `rating BETWEEN 1 AND 5`). Drop reviews where the text body is completely empty or whitespace-only during normalization.

### 1.4 Multilingual & Exotic Character Encodings
- **Edge Case**: User reviews written in non-English languages (Hindi, Spanish, Arabic), right-to-left scripts, or heavily laden with emojis and Unicode surrogate pairs.
- **Impact**: Tokenizer failures, sentiment skew, or display errors on legacy Windows consoles.
- **Mitigation / Behavior**: Store all text as UTF-8 in SQLite. In terminal output layers, sanitize characters or use ASCII replacements to avoid `UnicodeEncodeError` on `cp1252` environments.

---

## 2. Phase 2 — Clustering & LLM Summarization

### 2.1 Identical, Spam, or Bot Reviews
- **Edge Case**: Hundreds of reviews in a week consist of identical spam strings (e.g., `"good"`, `"nice app"`, `"best app ever"`, or promotional bot links).
- **Impact**: Embeddings cluster into a massive uninformative blob, dominating the weekly theme analysis.
- **Mitigation / Behavior**: Apply pre-clustering deduplication based on exact string matching or high Jaccard/Levenshtein similarity. Filter out ultra-short reviews (< 3 words) from theme clustering unless they represent a specific bug spike (e.g., `"app crash"`).

### 2.2 Dominant Cluster Splitting Infinite Loops
- **Edge Case**: A single cluster captures $> 60\%$ of all reviews, triggering recursive splitting. However, all reviews in that cluster have identical embeddings (e.g., coordinated review bombing), causing sub-clustering to return the exact same single cluster.
- **Impact**: Infinite recursion or stack overflow in the clustering pipeline.
- **Mitigation / Behavior**: Enforce a strict maximum recursion depth (`max_depth=3`) and check if sub-clustering produces more than 1 distinct cluster. If sub-clustering fails to divide the dataset, terminate splitting and accept the dominant cluster as a single broad theme.

### 2.3 LLM Quota Exhaustion & Transient 5xx Errors
- **Edge Case**: Groq or OpenAI APIs return HTTP `429 Rate Limit Exceeded`, `500 Internal Server Error`, or `503 Service Unavailable` during theme generation.
- **Impact**: Complete failure of the weekly summarization step.
- **Mitigation / Behavior**: Wrap LLM calls in a robust retry mechanism with exponential backoff (retrying up to 3 times for transient errors). If rate limits persist, fall back to an extractive summarization heuristic (e.g., top TF-IDF keywords and most upvoted reviews).

### 2.4 Malformed LLM JSON Outputs & Hallucinated Schemas
- **Edge Case**: The LLM returns invalid JSON, wraps JSON in markdown code blocks (` ```json ... ``` `), omits required schema keys (`theme_name`, `summary`, `action_ideas`), or includes trailing commas.
- **Impact**: `json.loads()` or Pydantic validation failures.
- **Mitigation / Behavior**: Implement regex-based pre-processing to strip markdown fences (`^```json|```$`). Use structured output prompting / Pydantic validators with automatic self-healing retry prompts if JSON parsing fails.

---

## 3. Phase 3 — Quote Verification & Rendering

### 3.1 LLM Quote Hallucination & Paraphrasing
- **Edge Case**: The LLM generates a quote that accurately captures the user's sentiment but is slightly paraphrased or re-worded rather than being an exact verbatim substring of an ingested review.
- **Impact**: Misrepresenting customer words to stakeholders or failing audit compliance.
- **Mitigation / Behavior**: The `QuoteValidator` strictly checks every LLM-proposed quote against the verbatim review corpus using exact string matching or normalized substring matching (ignoring case/punctuation). Hallucinated quotes that do not match verbatim text are automatically discarded or replaced with verified representative review snippets from that cluster.

### 3.2 Complete Verification Failure for a Theme
- **Edge Case**: Every single quote proposed by the LLM for a particular theme fails the verbatim validation check.
- **Impact**: A theme is rendered with an empty quotes section (`Quotes: None`), looking broken in reports.
- **Mitigation / Behavior**: When all LLM quotes for a theme fail validation, the renderer automatically selects the top 2 highest-confidence or most helpful reviews from that cluster's raw data as verified fallback quotes.

### 3.3 HTML / Markdown Injection & XSS in Reviews
- **Edge Case**: A malicious or unusual user review contains HTML tags, script injection, or markdown formatting characters (e.g., `<script>alert(1)</script>`, `| table | breaking |`, or `# Fake Header`).
- **Impact**: Broken layout in Google Docs/Markdown reports, or potential XSS when HTML teasers are viewed in webmail clients.
- **Mitigation / Behavior**: Escape all special characters (`<`, `>`, `&`, `"`, `'`) when generating HTML email bodies. Strip or escape markdown control characters (`|`, `#`, `*`, `_`) when formatting review quotes into markdown documents.

### 3.4 Terminal Console Encoding Compatibility (`cp1252` vs UTF-8)
- **Edge Case**: Running CLI commands on standard Windows command prompts or legacy CI/CD environments where `sys.stdout.encoding` is `cp1252`.
- **Impact**: Printing em-dashes (`—`), typographic quotes (`""`), or bullet points (`•`) throws fatal `UnicodeEncodeError`.
- **Mitigation / Behavior**: All CLI output and rendering templates use clean ASCII separators (`--` instead of `—`, `|` instead of `·`, `-` or `*` instead of Unicode bullets) or apply `.encode('ascii', 'replace').decode('ascii')` on terminal streams.

---

## 4. Phase 4 — Google Docs MCP Delivery

### 4.1 Malformed or URL-Wrapped Google Doc IDs
- **Edge Case**: The user configures `GOOGLE_DOC_ID` by pasting a full web browser URL (`https://docs.google.com/document/d/1n-S9qT-.../edit?tab=t.0`) instead of the raw alphanumeric document ID.
- **Impact**: Google Docs API calls fail with `400 Bad Request` or `404 Not Found` because the string contains slashes and query parameters.
- **Mitigation / Behavior**: `MCPClient._sanitize_doc_id()` automatically intercepts and strips URL prefixes and suffixes using regex (`([a-zA-Z0-9_-]{25,})`), extracting the clean alphanumeric ID before any network request is made.

### 4.2 Idempotency & Duplicate Run Executions
- **Edge Case**: A scheduled cron job or human operator triggers the Phase 4 delivery twice for the same product and ISO week (e.g., `groww-2026-W23`).
- **Impact**: The weekly report section gets appended twice, cluttering the Google Document with duplicate content.
- **Mitigation / Behavior**: `MCPClient.append_section()` performs an idempotent pre-flight search via `/search_doc` looking for the exact anchor (`groww-2026-W23`). If found, it short-circuits and returns `status: "already_exists"` without appending duplicate text.

### 4.3 Missing Server Endpoints & Legacy Container Deployments
- **Edge Case**: The remote MCP server container is running an older build that only exposes `/append_to_doc` and does not yet implement `/search_doc` (returning HTTP `404 Not Found`).
- **Impact**: Pre-flight idempotency checks cause the entire delivery pipeline to crash.
- **Mitigation / Behavior**: When `/search_doc` returns HTTP 404, the client catches the exception, logs a graceful warning (`"Server may be older version without search_doc. Proceeding gracefully."`), and falls back to executing `/append_to_doc`.

### 4.4 Google Drive Permissions & Quota Limits
- **Edge Case**: The configured Google Doc is private (service account lacks View/Edit permissions), deleted, or Google Docs API rate limits (read/write quotas) are exceeded.
- **Impact**: HTTP `403 Forbidden` or `429 Too Many Requests` from the MCP backend.
- **Mitigation / Behavior**: Non-transient errors (`403 Forbidden`, `404 Doc Not Found`) fail fast with clear actionable messages advising the user to check document sharing settings. Transient rate limits trigger automatic exponential backoff retries (`1s`, `2s`, `4s`).

---

## 5. Phase 5 — Gmail MCP Delivery

### 5.1 Empty or Malformed Recipient Lists
- **Edge Case**: Product configuration (`groww.yaml`) has an empty recipient list (`recipients: []`) or contains malformed email strings (`"not-an-email"`).
- **Impact**: Gmail API rejects the draft/send request with HTTP `400 Bad Request`.
- **Mitigation / Behavior**: Provide safe defaults (`recipients: ["stakeholders@example.com"]`) if YAML configuration is missing or empty. Validate basic email syntax before payload transmission. Automatically format list objects into comma-separated strings (`", ".join(to)`).

### 5.2 Draft-Only Production Container Environments
- **Edge Case**: The user requests `--email-mode send` (or calls `send_email`), but the remote MCP server container is deployed in a safe "draft-only" mode where `/send_email` is disabled or unrouted (returning HTTP `404 Not Found`).
- **Impact**: Email delivery fails completely, preventing stakeholders from being notified.
- **Mitigation / Behavior**: `MCPClient.send_email()` intercepts `404 Not Found` errors from `/send_email` and automatically downgrades/falls back to `/create_email_draft`, logging a warning and successfully generating a Gmail draft instead of losing the payload.

### 5.3 Email Client HTML Stripping & Styling Incompatibility
- **Edge Case**: Recipients view the weekly pulse email in strict email clients (e.g., text-only terminal mailers, legacy Outlook, or secure corporate gateways) that strip `<style>`, `<div>`, or HTML formatting.
- **Impact**: Unreadable, unstyled, or messy email presentation.
- **Mitigation / Behavior**: Every email teaser generated by `build_email_teaser()` outputs a dual-payload containing both inline-CSS styled HTML (`html_body`) and a cleanly formatted ASCII plain-text equivalent (`text_body`).

### 5.4 Payload Size Overflow
- **Edge Case**: An unusually verbose report generates an email body exceeding standard SMTP / Gmail draft size thresholds (> 1024 KB).
- **Impact**: API rejection or email truncation.
- **Mitigation / Behavior**: The email teaser is designed as a concise executive summary limiting output to the top 5 themes and brief bullet points, relying on the deep link (`Read Full Report -> https://docs.google.com/...`) to direct users to the complete document for extensive details.

---

## 6. Phase 6 — Orchestration, CLI & Audit Ledger

### 6.1 SQLite Database Locking (`database is locked`)
- **Edge Case**: Multiple CLI commands or background background worker processes attempt to write to the local audit ledger (`pulse_ledger.db`) simultaneously.
- **Impact**: `sqlite3.OperationalError: database is locked` exceptions causing job failures.
- **Mitigation / Behavior**: Configure SQLite connections with a timeout (`timeout=30.0`), enable Write-Ahead Logging (`PRAGMA journal_mode=WAL;`), and keep database transaction scopes as short as possible.

### 6.2 Partial Pipeline Execution & Retry State
- **Edge Case**: A full end-to-end pipeline run (`run-all`) completes Phase 1 (Ingestion), Phase 2 (LLM Summarization), and Phase 3 (Rendering), but crashes during Phase 4 (network failure while connecting to Railway MCP server).
- **Impact**: Re-running the pipeline from scratch would waste LLM tokens and re-scrape app store data.
- **Mitigation / Behavior**: The audit ledger tracks checkpoint status for each phase independently (`status: 'INGESTED'`, `'SUMMARIZED'`, `'DELIVERED_DOC'`, `'DELIVERED_EMAIL'`). When re-running for the same `(product, iso_week)`, the orchestrator resumes from the last successful checkpoint rather than restarting from zero.

### 6.3 Missing Environment Variables
- **Edge Case**: The CLI is executed on a fresh machine or container where `.env` is absent or variables (`GROQ_API_KEY`, `MCP_SERVER_URL`, `MCP_API_KEY`) are undefined.
- **Impact**: Mysterious `NoneType` errors or authorization failures during execution.
- **Mitigation / Behavior**: The CLI performs startup validation on `RunContext` initialization. If critical API keys or URLs are missing, it logs an explicit, user-friendly error instructing which variable to add to `.env` or pass via command-line flags.

---

## 7. Cross-Cutting Concerns

| Category | Corner Case | Handling Strategy |
| :--- | :--- | :--- |
| **Network** | DNS resolution failure or SSL handshake timeout to Railway MCP URL | Exponential backoff retries (up to 3 attempts); clear offline diagnostic error message. |
| **Security** | API Key leakage in console logs or traceback outputs | Ensure logging formatters sanitize/mask headers matching `X-API-Key` or `Authorization`. |
| **Timezones** | ISO week boundaries (`YYYY-Www`) across New Year transitions (e.g., Dec 31 vs Jan 1) | Use strict ISO 8601 calendar calculations (`datetime.isocalendar()`) to prevent week-number off-by-one errors. |
| **File System** | Missing `config/products/<slug>.yaml` file when running CLI | Gracefully fall back to internal default configuration dictionary without crashing. |
