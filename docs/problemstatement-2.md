# Problem Statement: Mutual Fund FAQ Assistant (Facts-Only Q&A)

> **Groww Use Case | RAG-Based | Strictly No Investment Advice**

---

## Overview

The objective of this project is to build a **facts-only FAQ assistant** for mutual fund schemes, using **Groww** as the reference product context. The assistant will answer **objective, verifiable queries** related to mutual funds by retrieving information exclusively from **official public sources**, such as AMC (Asset Management Company) websites, AMFI, and SEBI.

The system must strictly **avoid providing investment advice, opinions, or recommendations**. Every response must include a **single, clear source link** and adhere to defined constraints around clarity, accuracy, and compliance.

---

## Objective

Design and implement a lightweight **Retrieval-Augmented Generation (RAG)-based assistant** that:

- Answers **factual queries** about mutual fund schemes
- Uses a **curated corpus of official documents**
- Provides **concise, source-backed responses**

---

## Target Users

- Retail investors comparing mutual fund schemes
- Customer support and content teams handling repetitive mutual fund queries

---

## Scope of Work

### 1. Corpus Definition

- Select **one Asset Management Company (AMC)** — **HDFC Mutual Fund**
- Choose **5 mutual fund schemes** ensuring category diversity:

| # | Scheme | Category | Source URL (Groww) |
|---|---|---|---|
| 1 | HDFC Mid Cap Fund — Direct Growth | Mid Cap | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |
| 2 | HDFC Equity Fund — Direct Growth | Flexi Cap | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| 3 | HDFC Focused Fund — Direct Growth | Focused | https://groww.in/mutual-funds/hdfc-focused-fund-direct-growth |
| 4 | HDFC ELSS Tax Saver — Direct Plan Growth | ELSS | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| 5 | HDFC Large Cap Fund — Direct Growth | Large Cap | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |

> **Corpus scoping decision:** For this iteration, the corpus is **strictly limited to the 5 Groww scheme pages above**. No AMC PDFs (KIM/SID/factsheets), no AMFI pages, no SEBI pages, no AMC FAQ pages, and no other Groww pages are ingested or cited. Every fact the assistant returns must come from one of these 5 URLs — enforced via `sources.yaml` and a CI whitelist check.

---

### 2. FAQ Assistant Requirements

The assistant must answer **facts-only queries**, such as:

- Expense ratio of a scheme
- Exit load details
- Minimum SIP amount
- ELSS lock-in period
- Riskometer classification
- Benchmark index
- Process to download statements or capital gains reports

Every response must ensure:

- Each response is **limited to a maximum of 3 sentences**
- Each response includes **exactly one citation link** (from the 5-URL whitelist)
- Each response includes a footer: `"Last updated from sources: <date>"`

---

### 3. Refusal Handling

The assistant must **refuse non-factual or advisory queries**, such as:

- *"Should I invest in this fund?"*
- *"Which fund is better?"*

Refusal responses must:

- Be **polite and clearly worded**
- Reinforce the **facts-only limitation**
- Provide **exactly one relevant Groww scheme URL** from the whitelist (the matching scheme, or the first scheme if none resolved)

> **Note:** In this iteration, the educational link on refusals is always one of the 5 whitelisted Groww URLs — not an external AMFI/SEBI page.

---

### 4. User Interface (Minimal)

The solution must include a simple interface with:

- A **welcome message**
- **Three example questions** (clickable)
- A visible disclaimer: `"Facts-only. No investment advice."`

---

## Architecture Overview (Phase-wise RAG)

The build is structured across **6 phases**, each producing a working, demoable artifact.

### Phase 0 — Foundation & Governance
Lock down scope, sources, and guardrails before writing code.

- `config/sources.yaml` — exactly the 5 Groww URLs above, nothing else
- `config/refusal_intents.yaml` — advisory/comparison/prediction patterns + canned refusal copy
- `config/disclaimer.txt` — *"Facts-only. No investment advice."*

### Phase 1 — Ingestion & Corpus Build (Offline Pipeline)

```
URLs → Fetcher → Extractor → Cleaner → Chunker → Embedder → Indexer
                                                                  ↑
                                          Refresh & Health (orchestrates all above)
```

Sub-phases:

1. **1.1 Fetcher** — Pull 5 Groww HTML pages; persist raw snapshots with ETag tracking
2. **1.2 Extractor** — HTML → structured text with section anchors (Expense Ratio, Exit Load, Min SIP, etc.)
3. **1.3 Cleaner** — Strip boilerplate, normalize encoding, drop FAQ section and volatile fields (NAV, AUM)
4. **1.4 Chunker** — Section-aware splitting; ~7 chunks per scheme → ~35 chunks total; soft cap 250 tokens
5. **1.5 Embedder** — Dense vectors using `bge-small-en` (sentence-transformers) or `text-embedding-3-small`
6. **1.6 Indexer** — Build FAISS (dense) + BM25 (sparse) indexes with atomic swap
7. **1.7 Refresh & Health** — GitHub Actions scheduled pipeline; content-hash drift detection; freeze on mass drift

### Phase 2 — Retrieval Layer

```
Query → Normalizer → Scheme Resolver → Hybrid Retriever (Dense + BM25 + RRF)
      → Section Hint Boost → Cross-encoder Re-ranker → Confidence Gate
```

- Hybrid retrieval handles both exact token queries (₹500, 1%, 1 year) and semantic queries
- Confidence gate triggers *"I don't have a verified answer"* on low retrieval scores

### Phase 3 — Reasoning & Guardrails (Orchestrator)

**URL policy:**

| Situation | URLs in reply |
|---|---|
| PII detected in user message | **None** — locked `pii_block` template |
| Insufficient evidence / low confidence | **None** — `dont_know_without_link` |
| Non-factual intent (advisory/comparison) | **Exactly one** — matching Groww scheme URL from whitelist |
| Successful factual answer | **Exactly one** — `source_url` from top chunk (whitelist only) |

**LLM:** [Groq](https://groq.com) via OpenAI-compatible Chat Completions API (`GROQ_API_KEY`). Default auto-mode: Groq when key is set, extractive otherwise.

**Hard post-checks (deterministic):**
- Route-aware URL count enforcement
- Sentence count ≤ 3 for factual body
- No banned tokens (`recommend`, `should invest`, `better than`, `will outperform`)
- Footer present: `Last updated from sources: <YYYY-MM-DD>`

### Phase 4 — User Interface (Minimal Web App)

```
┌──────────────────────────────────────────────────────────────┐
│  Mutual Fund FAQ Assistant                                   │
│  Facts-only. No investment advice.            [disclaimer]   │
├──────────────────────────────────────────────────────────────┤
│  Welcome! Ask a factual question about HDFC schemes.         │
│                                                              │
│   • What is the expense ratio of HDFC Equity Fund?           │
│   • What is the exit load of HDFC Mid Cap Fund?              │
│   • What is the lock-in period for an ELSS fund?             │
├──────────────────────────────────────────────────────────────┤
│  [ type your question…                                 ] [→] │
├──────────────────────────────────────────────────────────────┤
│  Answer area                                                 │
│  ─ short answer (≤3 sentences)                               │
│  ─ Source: <single whitelisted link>                         │
│  ─ Last updated from sources: <date>                         │
└──────────────────────────────────────────────────────────────┘
```

**Stack:** FastAPI backend (`POST /ask`, `GET /meta`, `GET /health`) + minimal static SPA frontend (dark theme).

### Phase 5 — Evaluation, Compliance & Observability

| Suite | Pass Bar |
|---|---|
| Factual Q&A (30+ questions) | ≥ 90% exact-match / numeric tolerance |
| Citation correctness | 100% — cited URL contains the fact |
| Refusal suite (15+ questions) | 100% refused with whitelisted link |
| Out-of-corpus queries | 100% → "I don't have a verified answer" |
| PII probes | 100% rejected/redacted |
| Length & format | 100% — ≤ 3 sentences, 1 citation, footer |

CI gate: every URL in any answer must be in `sources.yaml`; no banned tokens; no PII in logs.

---

## What the Assistant Cannot Answer (This Iteration)

Because the corpus is limited to the 5 Groww product pages only, the assistant cannot answer:

- Tax-statement / capital-gains download walkthroughs
- Deep regulatory definitions from AMFI/SEBI
- Anything only present in KIM/SID PDFs not surfaced on the Groww product page

For these, the assistant returns: *"I don't have a verified answer for that. Please refer to: `<matching Groww scheme URL>`"*

---

## Constraints

### Data & Sources

| Rule | Detail |
|---|---|
| **Allowed sources** | The 5 whitelisted Groww scheme URLs only |
| **Prohibited sources** | AMC PDFs, AMFI, SEBI, third-party blogs, aggregators |
| **Citation integrity** | Every cited URL must string-match an entry in `sources.yaml` |
| **Corpus refresh** | GitHub Actions nightly/weekly; manual `workflow_dispatch` available |

### Privacy & Security

The system must **never** collect, store, or process:

- PAN or Aadhaar numbers
- Account numbers or OTPs
- Email addresses or phone numbers

All interactions are **stateless** — no user data persisted between sessions. Raw queries are **never** logged; only hashed for analytics.

### Content Restrictions

| Allowed | Not Allowed |
|---|---|
| Expense ratio facts | Return projections |
| Exit load details | Fund comparisons |
| SIP minimum amounts | Performance rankings |
| Lock-in periods | Investment suitability advice |
| Riskometer classification | Portfolio recommendations |
| Benchmark index | NAV trend analysis |

---

## Expected Deliverables

- **`config/sources.yaml`** — 5-URL whitelist registry
- **`config/refusal_intents.yaml`** — Refusal patterns and canned copy
- **`docs/architecture.md`** — Full phase-wise architecture document
- **`docs/edge_cases.md`** — Edge cases per phase
- **Ingestion pipeline** (`src/mf_faq/ingestion/`) — Phases 1.1–1.7
- **Retrieval layer** (`src/mf_faq/retrieval/`) — Phase 2
- **Orchestrator + guardrails** (`src/mf_faq/orchestrator/`) — Phase 3
- **FastAPI backend + SPA frontend** (`src/mf_faq/ui/`) — Phase 4
- **Eval harness + CI gate** (`tests/`) — Phase 5
- **GitHub Actions workflow** (`.github/workflows/`) — Scheduler
- **README** — Setup instructions, architecture overview, known limitations

---

## Success Criteria

- Accurate retrieval of factual mutual fund information
- Strict adherence to **facts-only responses**
- Consistent inclusion of **valid, whitelisted source citations**
- Proper refusal of all advisory, comparative, and prediction queries
- Zero PII collected, logged, or exposed
- Clean, minimal, and user-friendly interface with persistent disclaimer
- All Phase 5 eval suites passing in CI

---

## Deployment Options

| Option | Backend | Frontend |
|---|---|---|
| Option 1 | Streamlit | Streamlit |
| Option 2 (recommended) | Railway | Vercel |

Docker containerization recommended for dependency isolation.

---

## Disclaimer

> **Facts-only. No investment advice.**
> This assistant provides factual information about mutual fund schemes sourced exclusively from official Groww scheme pages. It does not provide investment advice, performance comparisons, return projections, or financial recommendations of any kind. Always consult a SEBI-registered investment advisor before making investment decisions.

---

*Version: 1.0.0 | AMC: HDFC Mutual Fund | Corpus: 5 Groww scheme URLs | LLM: Groq*
