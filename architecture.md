# Weekly Product Review Pulse — Architecture

This document describes the technical architecture for the Groww Play Store review pulse: components, data flows, MCP integration, idempotency, and operational concerns. It extends [problemStatement.md](problemStatement.md).

---

## 1. Goals and Constraints

| Goal | Architectural Implication |
| ---- | ------------------------ |
| Weekly insight report from Play Store reviews | Batch pipeline, not streaming |
| Google Doc as system of record | Append-only sections with stable anchors |
| Email as notification, not duplicate report | Teaser + deep link to Doc heading |
| MCP-only delivery to Google Workspace | Pulse agent never holds Google OAuth or calls REST directly |
| Idempotent weekly runs | Run ledger + deterministic section keys |
| Auditable history | Persist run metadata and delivery IDs |
| Safe LLM usage | PII scrubbing, quote validation, token/cost caps |

> **Current scope:** Groww · Google Play Store · Google Docs MCP + Gmail MCP (both deployed on Railway at `https://web-production-af4fc.up.railway.app`).

---

## 2. System Context

```mermaid
graph TB
    subgraph Stakeholders
        S1["Product / Support / Leadership"]
    end

    subgraph "This Repository"
        UI["FastAPI UI / Dashboard"]
        CLI["Pulse CLI / Scheduler"]
        Agent["Pulse Agent<br/>(MCP Host)"]
        Ingest["Play Store Ingestion"]
        Pipeline["Analysis Pipeline"]
        Renderer["Report & Email Renderer"]
        Ledger["Run Ledger"]
        DocsMCP["Google Docs MCP Server"]
        GmailMCP["Gmail MCP Server"]
    end

    subgraph External
        PlayStore["Google Play Store"]
        Groq["Groq API<br/>llama-3.3-70b-versatile"]
        SentenceTransformers["sentence-transformers<br/>BAAI/bge-small-en-v1.5"]
        DocsAPI["Google Docs API"]
        GmailAPI["Gmail API"]
    end

    subgraph "Google Workspace"
        Doc["Weekly Review Pulse — Groww<br/>(Google Doc)"]
        Inbox["Stakeholder Inboxes"]
    end

    UI --> Agent
    CLI --> Agent
    Agent --> Ingest
    Agent --> Pipeline
    Agent --> Renderer
    Agent --> Ledger

    Ingest --> PlayStore
    Pipeline --> Groq
    Pipeline --> SentenceTransformers

    Agent -- "stdio" --> DocsMCP
    Agent -- "stdio" --> GmailMCP

    DocsMCP --> DocsAPI --> Doc
    GmailMCP --> GmailAPI --> Inbox

    Doc --> S1
    Inbox --> S1
```

The pulse agent orchestrates ingestion, analysis, rendering, and delivery. It connects to in-repo MCP servers as an MCP client. Google credentials and API access are confined to those servers.

---

## 3. Logical Layers

```mermaid
graph LR
    subgraph "Layer 1 — Data Retrieval"
        A1["Play Store Scraper"]
        A2["Review Normalizer"]
    end
    subgraph "Layer 2 — Reasoning"
        B1["PII Scrubber"]
        B2["Embedder"]
        B3["UMAP + HDBSCAN"]
        B4["Groq Summarizer"]
        B5["Quote Validator"]
    end
    subgraph "Layer 3 — Output Generation"
        C1["Doc Section Builder"]
        C2["Email Teaser Builder"]
    end
    subgraph "Layer 4 — Delivery via MCP"
        D1["Docs MCP Tools"]
        D2["Gmail MCP Tools"]
    end

    A1 --> A2 --> B1 --> B2 --> B3 --> B4 --> B5 --> C1 --> D1
    B5 --> C2 --> D2
```

| Layer | Responsibility | Must Not |
| ----- | -------------- | -------- |
| **Data Retrieval** | Fetch and normalize Play Store reviews for Groww | Call Google Workspace APIs |
| **Reasoning** | Cluster, summarize, validate quotes | Write to Docs or Gmail |
| **Output Generation** | Build formatted Doc text content and email HTML/text | Hold Google OAuth |
| **Delivery** | Append Doc section, send/draft email | Contain clustering/LLM logic |

---

## 4. Repository Layout

```
Weekly Pulse/
├── docs/
│   ├── problemStatement.md
│   ├── architecture.md
│   ├── implementation-plan.md
│   └── edge-cases.md
├── config/
│   ├── products/
│   │   └── groww.yaml            # Play Store app id, doc id, recipients
│   ├── pipeline.yaml             # window weeks, cluster params, LLM limits
│   └── mcp/
│       ├── docs-mcp.env.example
│       └── gmail-mcp.env.example
├── mcp-servers/
│   ├── google-docs-mcp/          # MCP server: Docs append, heading lookup
│   └── gmail-mcp/                # MCP server: draft, send, idempotency keys
├── pulse/
│   ├── cli.py                    # Entry: run, backfill, dry-run
│   ├── agent/
│   │   ├── orchestrator.py       # End-to-end run coordinator
│   │   └── mcp_client.py         # MCP host wiring
│   ├── ingestion/
│   │   ├── play_store.py         # Scraper + pagination
│   │   ├── normalizer.py         # Quality filters (words, language, emoji)
│   │   ├── cache.py              # reviews_raw / reviews_normalized cache
│   │   └── models.py             # Review, RawReview, RunContext
│   ├── pipeline/
│   │   ├── scrubber.py           # PII redaction
│   │   ├── embeddings.py         # local sentence-transformers (BAAI/bge-small-en-v1.5)
│   │   ├── clustering.py         # UMAP + HDBSCAN
│   │   ├── summarizer.py         # LLM theme/quote/action generation
│   │   └── quote_validator.py    # Substring match against source reviews
│   ├── render/
│   │   ├── doc_section.py        # Formatted text content for Docs MCP
│   │   └── email_teaser.py       # HTML + plain text teaser
│   └── ledger/
│       ├── store.py              # SQLite or JSON run ledger
│       └── models.py             # RunRecord, DeliveryRecord
├── data/                         # gitignored: cached reviews, run artifacts
└── tests/
```

This layout keeps MCP servers, the pulse pipeline, and configuration separable while shipping everything from one repo.

---

## 5. End-to-End Run Flow

```mermaid
sequenceDiagram
    participant CLI as Pulse CLI
    participant Orch as Orchestrator
    participant Ingest as Ingestion
    participant Pipe as Pipeline
    participant Render as Renderer
    participant Ledger as Run Ledger
    participant Docs as Docs MCP
    participant Gmail as Gmail MCP

    CLI->>Orch: run --product groww --iso-week 2026-W23
    Orch->>Ledger: check idempotency (groww, 2026-W23)

    alt already completed
        Ledger-->>Orch: prior delivery ids
        Orch-->>CLI: skip (no-op success)
    else new or failed retry
        Orch->>Ingest: fetch_reviews(window=8-12w)
        Ingest-->>Orch: Review[]

        Orch->>Pipe: analyze(reviews)
        Pipe-->>Orch: PulseReport (themes, quotes, actions)

        Orch->>Render: build_outputs(report, iso_week)
        Render-->>Orch: DocSection, EmailTeaser

        Orch->>Docs: append_to_doc(doc_id, content)
        Docs-->>Orch: heading_id, doc_url_fragment

        Orch->>Gmail: send_or_draft(teaser, deep_link, idempotency_key)
        Gmail-->>Orch: message_id / draft_id

        Orch->>Ledger: record_run(metadata, delivery_ids)
        Orch-->>CLI: success + audit summary
    end
```

### Run Inputs

| Parameter | Description | Example |
| --------- | ----------- | ------- |
| `product` | Product slug | `groww` |
| `iso_week` | ISO 8601 week | `2026-W23` |
| `window_weeks` | Rolling review window | `10` (within 8–12 configurable range) |
| `dry_run` | Skip MCP writes | `false` |
| `email_mode` | `draft` or `send` | `draft` in staging |

### Run Outputs (Audit Record)

```json
{
  "run_id": "groww-2026-W23-abc123",
  "product": "groww",
  "iso_week": "2026-W23",
  "review_count": 872,
  "window_weeks": 10,
  "started_at": "2026-06-08T03:30:00+05:30",
  "completed_at": "2026-06-08T03:42:11+05:30",
  "doc_delivery": {
    "document_id": "...",
    "section_anchor": "groww-2026-W23",
    "heading_id": "...",
    "url": "https://docs.google.com/document/d/...#heading=..."
  },
  "email_delivery": {
    "mode": "draft",
    "message_id": "...",
    "idempotency_key": "groww-2026-W23-email"
  },
  "status": "completed"
}
```

---

## 6. Play Store Ingestion

### Responsibilities

1. Resolve Groww's Play Store listing from product config (`play_store_app_id` or package name).
2. Scrape public reviews within the configured date window (8–12 weeks).
3. Paginate until window boundary or no more pages.
4. Normalize to a canonical `Review` model.

### Review Models

**Raw cache** (`reviews_raw.json`) — full scrape payload per review:

| Field | Type | Notes |
| ----- | ---- | ----- |
| `text` | `string` | Raw review body |
| `rating` | `int` | 1–5 stars |
| `published_at` | `datetime` | UTC; used for window filtering |

**Normalized pipeline input** (`reviews_normalized.json`, `Review` in `models.py`) — what Phase 2 consumes:

| Field | Type | Notes |
| ----- | ---- | ----- |
| `text` | `string` | Review body passing quality filters |
| `rating` | `int` | 1–5 stars |

**Phase 1 normalization** (before cache write): ≥ 8 words, English-only (`allowed_language: en`), no emoji. Real Groww data (2026-06-23): **1,066 normalized reviews from 5,000 raw (~21% kept)**. 14 Devanagari-script reviews pass the Play Store `lang=en` filter and are caught by the Phase 2a script filter (see §7.1). Future fields (`review_id`, `published_at`, `language`) may be added without changing the scrub → embed → cluster flow.

### Design Decisions

- **Cache** raw and normalized pulls under `data/cache/{product}/{date}/` (`reviews_raw.json`, `reviews_normalized.json`, `manifest.json`) to avoid re-scraping on retries and to support audit ("what reviews were analyzed?").
- **Deduplicate** raw reviews by hash of `(text, rating, published_at)` before normalization.
- **Rate limiting** with backoff; ingestion failures abort the run before any Doc/email write.
- **No App Store adapter** in v1; interface `ReviewSource` allows future sources without changing downstream pipeline.

---

## 7. Analysis Pipeline

**Input:** `list[Review]` with `{ text, rating }` from normalized cache or ingestion.

**ML floor:** If normalized review count < 20, abort before embedding (orchestrator may also enforce `min_reviews` from product config).

### 7.1 PII Scrubbing & Language Filtering

Run **before** embedding, LLM calls, and publishing. Two steps:

**Step 1 — Non-English script filter** _(data-validated, added after Groww analysis)_

The Play Store `lang=en` parameter does not fully suppress Indic-script reviews. Real Groww data contained **14 Devanagari-script reviews** that passed Phase 1 normalization (they had ≥ 8 Latin characters embedded). These are dropped before embedding to prevent noisy cluster outliers. Hinglish (Hindi in Latin script, 72 reviews found) is **kept** — it embeds meaningfully and reflects real user sentiment.

```python
def is_latin_dominant(text: str) -> bool:
    ascii_chars = sum(1 for c in text if c.isascii())
    return len(text) == 0 or (ascii_chars / len(text)) >= 0.80
```

Drop reviews where `< 80%` of characters are ASCII; log the count per run.

**Step 2 — PII redaction**

| Pattern Class | Action |
| ------------- | ------ |
| Email addresses | Redact → `[EMAIL]` |
| Phone numbers (IN formats) | Redact → `[PHONE]` |
| Long numeric sequences (PAN/Aadhaar-like) | Redact → `[ID]` |
| URLs with tokens | Redact path/query |
| Financial amounts (₹10k, lakhs, $…) | **Keep in v1** — useful theme signal, not treated as PII |

Scrubbed text is used for embedding, LLM prompts, Doc output, and quote validation. Raw text stays in `reviews_raw.json` only (gitignored). The quote validator always compares against **scrubbed** cluster text.

### 7.2 Embeddings and Clustering

```mermaid
flowchart TD
    A["Script-filtered + scrubbed reviews<br/>(text + rating)"] --> B{"count ≥ 20?"}
    B -- "no" --> C["Abort run"]
    B -- "yes" --> D["sentence-transformers BAAI/bge-small<br/>batch encode"]
    D --> E["UMAP<br/>random_state=42"]
    E --> F["HDBSCAN<br/>min_cluster_size=5"]
    F --> G["Rank: score = size × (6 − avg_rating)"]
    G --> H{"Dominant cluster > 60%?"}
    H -- "yes" --> HA["Mandatory rating split<br/>1-2★ vs 4-5★ sub-clusters"]
    H -- "no" --> I["Rating-stratified sample<br/>8 reviews per top cluster"]
    HA --> I
    I --> J["Top N clusters → Groq"]
```

| Parameter | Typical Default | Config Key |
| --------- | --------------- | ---------- |
| Embedding provider / model | sentence-transformers / `BAAI/bge-small-en-v1.5` | `pipeline.embedding.*` |
| Embedding cache key | `sha256(scrubbed_text + rating)` | until `review_id` exists on `Review` |
| UMAP `n_neighbors` | 15 | `pipeline.clustering.umap.n_neighbors` |
| UMAP `n_components` | 5 | `pipeline.clustering.umap.n_components` |
| UMAP `random_state` | 42 | `pipeline.clustering.umap.random_state` |
| HDBSCAN `min_cluster_size` | 5 | `pipeline.clustering.hdbscan.min_cluster_size` |
| Top clusters to summarize | 3–5 | `pipeline.summarization.max_themes` |
| Samples per cluster | **8, rating-stratified** | `pipeline.summarization.max_samples_per_cluster` |

**Cluster ranking:** `score = cluster_size × (6 − avg_rating)` — prioritizes large low-star complaint themes. Real Groww data: **45% 1★ reviews** across overlapping complaint topics — ranking correctly surfaces the highest-signal pain points.

**Noise cluster** (label = −1) reviews are excluded from theme generation unless volume exceeds a configurable threshold.

**Clustering fallbacks** (see [edge-cases.md](edge-cases.md) §3):

| Condition | Behavior |
| --------- | -------- |
| All noise | Lower `min_cluster_size` once; if still all noise, abort or single rating-stratified LLM pass |
| One cluster > 60% of corpus | **Mandatory** rating split (1–2★ vs 4–5★ sub-clusters) before re-rank. Threshold lowered from 80%: Groww's 45% 1★ skew would easily create a dominant complaint cluster without this guard |
| Many micro-clusters | Take top `max_themes` by score only |

### 7.3 LLM Summarization (Groq)

**Provider:** Groq — `llama-3.3-70b-versatile`. Embeddings remain purely local via `sentence-transformers`; only summarization uses Groq (`GROQ_API_KEY`).

**Call pattern:** One Groq request per top cluster (not one mega-prompt). Sequential calls with ≥ 2s interval — no parallel LLM requests.

**Groq rate limits — `llama-3.3-70b-versatile`:**

| Limit | Value | Pipeline Enforcement |
| ----- | ----- | -------------------- |
| Requests / Minute | 30 | `request_interval_seconds: 2` (max 30/min safe) |
| Requests / Day | 1,000 | ≤ 10 req/run (5 themes + ≤ 5 re-prompts) → 100 runs/day headroom |
| Tokens / Minute | 12,000 | Pre-flight token estimate per request; drop longest samples if over budget |
| Tokens / Day | 100,000 | Cap `max_tokens_per_run: 12,000` → ~8 runs/day headroom |

**Rating-stratified sampling** _(data-validated, added after Groww analysis)_

Real Groww clusters contain 100–140 reviews each. Random sampling risks the LLM seeing only the most generic phrasing. Instead, sample **8 reviews proportionally by star rating within each cluster** — ensuring the LLM sees the full sentiment range at no extra token cost.

```python
# Example: cluster is 80% 1★, 20% 2★ → sample 6 from 1★, 2 from 2★
def stratified_sample(cluster_reviews, n=8):
    by_rating = {}
    for r in cluster_reviews:
        by_rating.setdefault(r.rating, []).append(r)
    total = len(cluster_reviews)
    samples = []
    for rating, group in sorted(by_rating.items()):
        quota = max(1, round(n * len(group) / total))
        samples.extend(random.sample(group, min(quota, len(group))))
    return samples[:n]
```

**Token budget per request (design target):**

| Component | Tokens |
| --------- | ------ |
| System prompt | ~200 |
| 8 review samples × ~150 tokens | ~1,200 |
| Output JSON per theme | ~300 |
| **Total per call** | **~1,700** |
| Per full run (5 themes) | **~8,500** — within 12K TPD cap per run |

**Output schema (per theme):**

```json
{
  "theme_name": "App performance & bugs",
  "summary": "Lag and crashes during trading hours; session timeouts.",
  "sentiment": "NEGATIVE",
  "teams": ["Android Eng", "Backend Ops"],
  "quotes": ["The app freezes exactly when the market opens..."],
  "action_ideas": [
    {
      "title": "Stabilize peak-time performance",
      "detail": "Scale infra during market hours; improve crash visibility."
    }
  ]
}
```

**Prompt safety:**

- Reviews wrapped as untrusted user data block (XML/markdown fenced).
- System instruction: explicitly ignore instructions embedded in review text (prompt injection guard).
- Pre-flight token estimate; if over budget, drop longest samples first.
- Retry HTTP 429/529 with exponential backoff (max 3 retries, cap 60s).
- Log per run: requests made, input tokens, output tokens, running daily totals vs caps.
- Re-prompt once per cluster if all quotes fail (counts toward RPM/RPD); omit theme if still invalid.

### 7.4 Quote Validation

Every Groq-produced quote must pass validation before inclusion in the report:

1. Normalize whitespace and punctuation on quote and candidate review texts.
2. Require **case-insensitive substring match** against at least one scrubbed review in the same cluster; fallback to the full scrubbed corpus.
3. Accept ellipsis truncation (`...` / `…`) as prefix match **only if the matched prefix is ≥ 15 characters**. Groww reviews commonly end sentences with trailing `....` as casual punctuation (not truncation) — a short prefix would cause false-positive matches.
4. Typos and Hinglish-in-English: case-insensitive match only — no translation required.
5. Quotes failing validation are **dropped and logged**; if a theme loses all quotes, re-prompt once or omit the theme.

> This prevents hallucinated "user quotes" from reaching stakeholders.

---

## 8. Output Generation

### 8.1 Google Doc Section Structure

Each weekly run appends one section to *Weekly Review Pulse — Groww*:

```
Heading 1: Groww — Weekly Review Pulse — 2026-W23
  Paragraph: Period: Last 10 weeks (rolling) · Source: Google Play Store · Generated: 2026-06-08 IST

  Heading 2: Top themes
    Bulleted list (theme name — summary)

  Heading 2: Real user quotes
    Bulleted list (verbatim validated quotes)

  Heading 2: Action ideas
    Bulleted list (title — detail)

  Heading 2: Who this helps
    Short table or bullets (Product / Support / Leadership)
```

The orchestrator passes formatted text content (`content: str`) directly to the Docs MCP `/append_to_doc` endpoint. Since the MCP server does not support rich formatting, the text is formatted cleanly with markdown headers and bullets for scannability.

### 8.2 Section Anchor (Idempotency)

| Concept | Value |
| ------- | ----- |
| Anchor key | `{product}-{iso_week}` e.g. `groww-2026-W23` |
| Heading text | `Groww — Weekly Review Pulse — 2026-W23` |
| Stored metadata | `heading_id`, document `revision_id` after write |

**Idempotent Doc write behavior:**

1. Docs MCP searches the document for an existing heading matching the anchor key (custom heading property or deterministic heading text).
2. If found → return existing `heading_id` and URL fragment; **do not append again**.
3. If not found → append section at end (or configured insertion point).

### 8.3 Email Teaser

Email body is intentionally short:

- **Subject:** `Groww Weekly Review Pulse — 2026-W23`
- **Body:** 3–5 bullet theme headlines + one-line context
- **CTA:** *Read full report →* deep link to Doc section (`#heading={heading_id}` or equivalent)
- **Footer:** generation timestamp, review window, link to full Doc

> Full report content lives **only** in the Doc.

---

## 9. MCP Server Architecture

Both services (Docs and Gmail) are provided by a deployed MCP-style server hosted on Railway at `https://web-production-af4fc.up.railway.app` (configured via `MCP_SERVER_URL`; repository: `https://github.com/Jagriti30/mcp-server-jagriti/`). The pulse agent communicates with it via REST/HTTP endpoints.

```mermaid
graph LR
    Agent["Pulse Agent<br/>(MCP Client)"]

    subgraph "Railway Hosted MCP Server (web-production-af4fc.up.railway.app)"
        DT1["/append_to_doc"]
        DT2["/search_doc"]
        GT1["/create_email_draft"]
        DC["Google Docs API Client"]
        GC["Gmail API Client"]
    end

    Agent -- "HTTP POST" --> DT1
    Agent -- "HTTP POST" --> DT2
    Agent -- "HTTP POST" --> GT1

    DT1 --> DC
    DT2 --> DC
    GT1 --> GC

    DC --> DocsAPI["Google Docs API"]
    GC --> GmailAPI["Gmail API"]
```

### 9.1 Google Docs Delivery

| Endpoint | Purpose | Key Inputs |
| -------- | ------- | ---------- |
| `/search_doc` | Idempotency lookup | `doc_id`, `anchor` |
| `/append_to_doc` | Add weekly section | `doc_id`, `content` |

**Idempotency fallback:** If `/search_doc` returns a 404 (e.g. older server version), the agent will gracefully skip the check and proceed to append.

**Credential handling:** The agent authenticates to the railway server using an `X-API-Key` configured via `MCP_API_KEY`. Google OAuth credentials (`credentials.json` and `token.json`) are injected into the Railway server via the `GOOGLE_CREDENTIALS_JSON` and `GOOGLE_TOKEN_JSON` raw JSON environment variables, avoiding the need to commit them to the repository or deploy them as files.

### 9.2 Gmail Delivery

| Endpoint | Purpose | Key Inputs |
| -------- | ------- | ---------- |
| `/create_email_draft` | Create draft | `to`, `subject`, `body` |

**Idempotency:** Prevent duplicate sends by relying on the local Pulse Agent's run ledger.

### 9.3 Pulse Agent MCP Client

The agent:

1. Configures the remote server URL from the `MCP_SERVER_URL` environment variable (defaulting to `https://web-production-af4fc.up.railway.app`).
2. Connects over HTTP POST using `httpx`.
3. Calls endpoints in order during the delivery phase.
4. **Never imports Google API client libraries for delivery.**


---

## 10. Run Ledger and Audit

Central run ledger (SQLite recommended) owned by the pulse agent, written after successful MCP delivery.

### Table: `runs`

| Column | Description |
| ------ | ----------- |
| `run_id` | UUID |
| `product` | `groww` |
| `iso_week` | `2026-W23` |
| `status` | `pending`, `completed`, `failed` |
| `review_count` | int |
| `window_weeks` | int |
| `started_at`, `completed_at` | timestamps |
| `error_message` | nullable |
| `report_json` | TEXT (cached PulseReport JSON for Analytics Dashboard) |

### Table: `deliveries`

| Column | Description |
| ------ | ----------- |
| `run_id` | FK → `runs` |
| `channel` | `google_doc`, `gmail` |
| `external_id` | `heading_id`, `message_id`, `draft_id` |
| `url` | Doc or Gmail link |
| `idempotency_key` | nullable |

**Unique constraint:** `(product, iso_week)` on `runs` where `status = completed` — enforces at-most-one successful run per week at the orchestrator level, complementing MCP-level checks.

---

## 11. Configuration

### Product Config — `config/products/groww.yaml`

```yaml
product: groww
display_name: Groww
play_store:
  app_id: com.nextbillion.groww  # example; verify at build time
ingestion:
  window_weeks: 10
  min_reviews: 20
  max_reviews: 5000
  min_words: 8
  allowed_language: en
delivery:
  google_doc_id: "<SHARED_DOC_ID>"
  email:
    recipients:
      - product-leads@example.com
      - support-leads@example.com
    default_mode: draft  # draft | send
```

### Pipeline Config — `config/pipeline.yaml`

```yaml
embedding:
  provider: sentence-transformers
  model: BAAI/bge-small-en-v1.5
  batch_size: 64
clustering:
  umap:
    n_neighbors: 15
    n_components: 5
    metric: cosine
  hdbscan:
    min_cluster_size: 5
    min_samples: 3
summarization:
  provider: groq
  model: llama-3.3-70b-versatile
  max_themes: 5
  max_tokens_per_run: 12000
  max_samples_per_cluster: 8
  max_output_tokens_per_theme: 800
  request_interval_seconds: 2
safety:
  scrub_pii: true
  max_review_chars: 2000
```

Environment-specific overrides via env vars (e.g. `PULSE_EMAIL_MODE=send`, `GROQ_API_KEY` for summarization, `MCP_SERVER_URL` for MCP host defaulting to `https://web-production-af4fc.up.railway.app`).

---

## 12. CLI and Scheduling

### CLI Commands

| Command | Description |
| ------- | ----------- |
| `pulse run --product groww [--iso-week YYYY-Www]` | Run for current or specified ISO week |
| `pulse backfill --product groww --from 2026-W01 --to 2026-W20` | Sequential backfill with idempotency |
| `pulse dry-run --product groww` | Full pipeline except MCP writes |
| `pulse status --product groww --iso-week 2026-W23` | Show ledger + delivery ids |

**Default ISO week:** Week containing the run date, or previous complete week if running Monday morning IST before reviews stabilize (configurable policy).

### Scheduler

- Cron / GitHub Actions / Cloud Scheduler invokes `pulse run --product groww` weekly (e.g. Monday 09:00 IST).
- Scheduler passes secrets (`GROQ_API_KEY`, embedding provider key) via env; Google secrets stay with MCP servers only.

---

## 13. Security and Safety

| Risk | Mitigation |
| ---- | ---------- |
| Google OAuth leakage | Credentials injected into MCP server via environment variables (`GOOGLE_CREDENTIALS_JSON`, `GOOGLE_TOKEN_JSON`); gitignored locally |
| PII in reports | Scrubber before LLM and publish |
| Prompt injection via reviews | Data/non-instruction framing; no tool execution from review text |
| Hallucinated quotes | Substring validator against source reviews |
| Runaway LLM cost / Groq rate limits | `max_tokens_per_run`, per-cluster sample caps, sequential requests, 429 backoff |
| Duplicate stakeholder email | Idempotency key + ledger + Docs anchor |
| Scraping abuse / blocks | Rate limits, retries, user-agent policy |

---

## 14. Error Handling and Partial Failure

| Failure Point | Behavior |
| ------------- | -------- |
| Ingestion fails | Abort; no Doc/email; ledger → `failed` |
| Pipeline/LLM fails | Abort; no Doc/email; ledger → `failed` |
| Doc append succeeds, Gmail fails | Ledger → `failed` with partial delivery; retry safe via idempotency (Doc no-op, Gmail retried) |
| Gmail succeeds, ledger write fails | Log critical alert; MCP idempotency still prevents duplicate email on retry |

**Retries:** Orchestrator may retry transient MCP errors with exponential backoff (max 3). Non-transient errors (auth, invalid doc id) fail fast.

---

## 15. Observability

| Signal | Mechanism |
| ------ | --------- |
| Structured logs | JSON logs per stage with `run_id`, `product`, `iso_week` |
| Metrics | Review count, cluster count, Groq requests/tokens, embedding batch count, duration per stage |
| Artifacts | Optional JSON report snapshot in `data/runs/{run_id}/` |
| Audit queries | CLI `status` + SQL against ledger |

---

## 16. Environments

| Environment | Email Mode | Doc Target | Notes |
| ----------- | ---------- | ---------- | ----- |
| Local dev | `draft` | Test Doc id | `dry-run` available |
| Staging | `draft` | Staging Doc | Requires explicit `--send` to override |
| Production | `send` | Production Doc | Scheduler default |

---

## 17. Testing Strategy

| Layer | Approach |
| ----- | -------- |
| Ingestion | Fixture HTML/JSON snapshots; no live scrape in unit tests |
| Scrubber / validator | Table-driven tests on synthetic PII and quotes |
| Clustering | Golden-file tests on fixed embedding inputs |
| Summarizer | Mock Groq client; schema validation; rate-limit retry tests |
| Docs/Gmail MCP | Contract tests with mocked Google API |
| Orchestrator | Integration test: full run with MCP mocks + ledger idempotency |
| E2E (manual) | One dry-run and one draft email against real Google APIs in staging |

---

## 18. Future Expansion (Out of Scope for v1)

Architectural extension points already implied by the design:

| Extension | Touch Points |
| --------- | ------------ |
| Additional products | New `config/products/*.yaml`; reuse pipeline + MCP |
| App Store RSS | New `ingestion/app_store.py` implementing `ReviewSource` |
| Multi-source merge | Fan-in before embed step; `source` dimension on `Review` |
| Richer MCP | Additional tools only if pulse needs them; avoid generic Workspace scope |

---

## 19. Architecture Decision Summary

| Decision | Choice | Rationale |
| -------- | ------ | --------- |
| Delivery to Google | In-repo MCP servers | Matches problem constraint; isolates OAuth |
| Doc as source of truth | Append sections with anchors | History + idempotency + stakeholder link target |
| Email content | Teaser + deep link | Avoid duplicate maintenance |
| Language filter (Phase 2a) | Latin-dominance check (≥ 80% ASCII) | Play Store `lang=en` does not fully suppress Devanagari; 14 such reviews found in real Groww data |
| Clustering | UMAP + HDBSCAN | Unsupervised theme discovery without fixed taxonomy |
| Cluster ranking | `size × (6 − avg_rating)` | Surfaces actionable low-star complaint themes; 45% 1★ skew in Groww data validates this |
| Dominant-cluster threshold | 60% (mandatory split) | Lowered from 80%: Groww's 1★ skew creates a large complaint cluster that would obscure distinct sub-themes at 80% |
| LLM sample selection | 8 reviews, rating-stratified per cluster | Clusters of 100–140 reviews; stratification ensures LLM sees full sentiment range at no extra token cost |
| Summarization LLM | Groq `llama-3.3-70b-versatile` | Cost-effective; ~1,700 tokens/call, ~8,500/run — well within 12K TPM and 100K TPD limits |
| Embeddings | `sentence-transformers` BAAI/bge-small | Fully local, zero API cost, batch-friendly for ~1,000+ reviews |
| Quote ellipsis rule | ≥ 15-char prefix required | Reviewers use trailing `....` as punctuation; short-prefix match causes false-positives |
| Quote trust | Post-LLM substring validation against scrubbed text | Prevents fabricated user voice |
| Idempotency | Anchor + email key + ledger | Safe weekly cron and backfill |
| v1 scope | Groww Play Store only | Reduce ingestion and config surface |

---

## 20. Related Documents

- [problemStatement.md](problemStatement.md) — Product intent, requirements, and non-goals
- [implementation-plan.md](implementation-plan.md) — Phase-wise build plan and exit criteria
- [edge-cases.md](edge-cases.md) — Clustering fallbacks, quote validation, and failure modes
