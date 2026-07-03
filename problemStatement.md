# Weekly Product Review Pulse — Problem Statement

We are building an **automated weekly "pulse"** that turns public Google Play Store reviews for selected fintech products into a one-page insight report and delivers it to stakeholders through Google Workspace, using **MCP (Model Context Protocol)** so that writes to Google Docs and Gmail go through dedicated MCP servers — not ad-hoc API calls inside the agent.

> **v1 Scope:** Groww · Google Play Store only.

---

## Objective

Give product, support, and leadership teams a **repeatable, weekly snapshot** of what customers are saying in store reviews: themes, representative quotes, and actionable ideas — without manual copy-paste or one-off spreadsheets.

---

## What the System Does

1. **Ingest** public reviews from the last 8–12 weeks (configurable rolling window) from the Google Play Store for the target product.
2. **Cluster and rank** feedback using embeddings and density-based clustering (UMAP + HDBSCAN), then use an LLM to name themes, pull verbatim quotes, and propose action ideas — with validation so quotes must appear in real review text.
3. **Render** a concise one-page narrative: top themes, quotes, action ideas, and a short "who this helps" section.
4. **Deliver** outputs only through Google Workspace MCP servers:
   - **Google Docs MCP** — Append each week's report as a new dated section to a single running document per product (e.g. *Weekly Review Pulse — Groww*). The Doc is the system of record and preserves history.
   - **Gmail MCP** — Send a short stakeholder email that includes a deep link to the new section in that Doc (heading link), not a duplicate full report in email alone.

### Internal Modularity

| Concern                 | Where it lives                                                                 |
| ----------------------- | ------------------------------------------------------------------------------ |
| Data retrieval          | Ingestion modules (Play Store scraper)                                         |
| Reasoning               | Clustering + LLM summarization (themes, quotes, actions)                       |
| Output generation       | Report + email rendering (structured for Docs and HTML/text for Gmail)         |
| Human-visible delivery  | MCP tools only → Google Docs MCP + Gmail MCP                                  |

> The agent is an MCP host/client; it does **not** embed Google credentials or call the Docs/Gmail REST APIs directly for delivery.

---

## Key Requirements

| #  | Requirement           | Detail                                                                                                                                                                              |
| -- | --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1  | **MCP-based delivery** | Append to the shared Google Doc and send Gmail only via the respective MCP servers' tools (e.g. document batch update, draft/create/send flows as defined in architecture).           |
| 2  | **Weekly cadence**     | Designed to run once per product per week (e.g. scheduled job Monday morning IST), with a CLI for backfill of any ISO week.                                                         |
| 3  | **Idempotent runs**    | Re-running the same product + ISO week must not create duplicate Doc sections or duplicate sends. Enforced with a stable section anchor in the Doc and a run-scoped idempotency check on email. |
| 4  | **Auditable**          | Each run records delivery identifiers (e.g. doc heading / message ids) and enough metadata to answer "what was sent when, for which week?"                                           |
| 5  | **Safety & quality**   | PII scrubbing on review text before LLM and before publishing; reviews treated as data, not instructions; cost/token limits per run.                                                 |

---

## Non-Goals (Explicit)

- A generic Google Workspace product beyond what the pulse needs (Docs append + Gmail send/draft).
- Real-time streaming analytics (batch analytics via the web dashboard are supported, but the Google Doc remains the primary artifact).
- Social sources (Twitter, Reddit, etc.) in the initial scope.
- Storing Google OAuth secrets in the agent codebase — they belong in the MCP servers' configuration, per architecture.
- Apple App Store ingestion in v1.

---

## Who This Helps

| Audience    | Value                                                  |
| ----------- | ------------------------------------------------------ |
| **Product**    | Prioritize roadmap from recurring themes               |
| **Support**    | Spot repeating complaints and quality issues            |
| **Leadership** | Fast health snapshot tied to customer voice             |

---

## Sample Output (Illustrative)

### Groww — Weekly Review Pulse

**Period:** Last 8–12 weeks (rolling window)

#### Top Themes

- **App performance & bugs** — Lag, crashes during trading hours; login/session timeouts.
- **Customer support friction** — Slow responses; unresolved tickets.
- **UX & feature gaps** — Confusing navigation for portfolio insights; missing advanced analytics.

#### Real User Quotes

> *"The app freezes exactly when the market opens, very frustrating."*

> *"Support takes days to reply and doesn't solve the issue."*

> *"Good for beginners but lacks detailed analysis tools."*

#### Action Ideas

| Action                              | Detail                                                                |
| ----------------------------------- | --------------------------------------------------------------------- |
| Stabilize peak-time performance     | Scale infra during market hours; improve crash visibility.             |
| Improve support SLA visibility      | Expected response time in-app; ticket status tracking.                 |
| Enhance power-user features         | Advanced portfolio analytics; clearer investments navigation.          |

#### What This Solves

Same intent as today: roadmap alignment for product, issue clustering for support, and a leadership-friendly snapshot — now automated, archived in Google Docs, and announced by email with a link back to the canonical section.

---

## Delivery Expectations (Stakeholder-Facing)

1. Each run adds **one clearly labeled section** to the product's pulse Google Doc (dated / week-labeled).
2. The email is a **brief teaser** (e.g. top themes as bullets) plus a *"Read full report"* link to that section.
3. Development/staging may default to **draft-only email** until explicit confirmation to send, per implementation plan.

---

## Supported Products (v1)

| Product | Platform          | Status     |
| ------- | ----------------- | ---------- |
| Groww   | Google Play Store | ✅ Active   |

Future candidates (post-v1): INDMoney, PowerUp Money, Wealth Monitor, Kuvera — with both App Store and Play Store coverage.

---

## Related Documents

- [`architecture.md`](architecture.md) — Technical architecture, data flows, MCP integration, idempotency
- [`implementation-plan.md`](implementation-plan.md) — Phase-wise build plan and exit criteria
- [`edge-cases.md`](edge-cases.md) — Clustering fallbacks, quote validation, and failure modes
