# Mutual Fund FAQ Assistant
**Facts-Only RAG System | Groww Use Case | HDFC Mutual Fund**

> **Facts-only. No investment advice.**

A lightweight Retrieval-Augmented Generation (RAG) assistant that answers strictly **factual, verifiable questions** about 5 HDFC Mutual Fund schemes listed on Groww — without providing investment advice, comparisons, or recommendations.

---

## Quick Start (Local Dev)

```bash
# 1. Clone and set up environment
git clone <repo-url>
cd mf-faq-assistant
cp .env.example .env          # Fill in GROQ_API_KEY

# 2. Create a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
pip install -e .              # Install mf_faq package in editable mode

# 4. Validate Phase 0 config (must pass before anything else)
python -m mf_faq.config.loader

# 5. Run the ingestion pipeline (Phase 1 — builds the index)
# TODO: Available after Phase 1 is implemented
# python -m mf_faq.ingestion.refresh

# 6. Start the API server (Phase 4)
# TODO: Available after Phase 4 is implemented
# uvicorn mf_faq.ui.app:app --reload

# 7. Open the frontend
# http://localhost:8000
```

---

## Docker

```bash
cp .env.example .env
# Fill in GROQ_API_KEY in .env
docker-compose up --build
```

---

## Corpus

The assistant's knowledge is **strictly limited** to these 5 Groww scheme pages:

| # | Scheme | Category |
|---|---|---|
| 1 | HDFC Mid Cap Fund — Direct Growth | Mid Cap |
| 2 | HDFC Equity Fund — Direct Growth | Flexi Cap |
| 3 | HDFC Focused Fund — Direct Growth | Focused |
| 4 | HDFC ELSS Tax Saver — Direct Plan Growth | ELSS |
| 5 | HDFC Large Cap Fund — Direct Growth | Large Cap |

No other sources are ingested or cited. This is enforced via `config/sources.yaml` and the CI whitelist gate.

---

## Architecture (6 Phases)

| Phase | Description | Status |
|---|---|---|
| **Phase 0** | Foundation & Governance | ✅ Complete |
| **Phase 1** | Ingestion & Corpus Build | 🔲 Stub |
| **Phase 2** | Retrieval Layer | 🔲 Stub |
| **Phase 3** | Reasoning & Guardrails | 🔲 Stub |
| **Phase 4** | User Interface (FastAPI + SPA) | 🔲 Stub |
| **Phase 5** | Evaluation, Compliance & CI | 🔲 Stub |

See [`docs/architecture.md`](docs/architecture.md) for the full phase-wise architecture.
See [`docs/edge_cases.md`](docs/edge_cases.md) for 94 per-phase edge cases.

---

## Project Structure

```
mf-faq-assistant/
├── config/                          # Phase 0 — Immutable governance files
│   ├── sources.yaml                 # 5-URL corpus whitelist
│   ├── refusal_intents.yaml         # Refusal patterns + canned copy
│   ├── disclaimer.txt               # Legal disclaimer text
│   └── thresholds.yaml              # Tunable numeric parameters
│
├── src/mf_faq/
│   ├── config/loader.py             # Phase 0 — Config loader & validator
│   ├── ingestion/                   # Phase 1 — fetcher, extractor, cleaner,
│   │                                #            chunker, embedder, indexer, refresh
│   ├── retrieval/                   # Phase 2 — normalizer, scheme_resolver,
│   │                                #            hybrid_retriever, section_booster,
│   │                                #            reranker, confidence_gate
│   ├── orchestrator/                # Phase 3 — pii_detector, intent_classifier,
│   │                                #            llm_client, post_checker, orchestrator
│   └── ui/                          # Phase 4 — app.py, routes/, static/
│
├── tests/
│   ├── eval/                        # Phase 5 eval YAML suites
│   ├── unit/                        # Unit tests per module
│   └── ci_gate.py                   # CI gate (URL whitelist + banned tokens + PII)
│
├── data/
│   ├── raw/                         # Fetched HTML (gitignored)
│   └── index/live/                  # FAISS + BM25 index (gitignored)
│
├── .github/workflows/
│   ├── ingest.yml                   # Weekly corpus refresh
│   └── eval.yml                     # Eval CI gate on every PR
│
├── docs/
│   ├── problemstatement-2.md        # Original problem statement
│   ├── architecture.md              # Full phase-wise architecture
│   └── edge_cases.md                # 94 per-phase edge cases
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
└── .env.example
```

---

## What the Assistant Can Answer

- Expense ratio (TER) of each scheme
- Exit load details
- Minimum SIP / lump-sum investment amounts
- ELSS lock-in period (3 years from date of investment)
- Riskometer classification
- Benchmark index

## What the Assistant Cannot Answer

- Tax statement / capital-gains download walkthroughs
- Deep regulatory definitions from AMFI/SEBI
- Anything only in KIM/SID PDFs not on the Groww scheme page
- Any question about non-HDFC AMC funds
- Investment advice, comparisons, or return projections (refused)

---

## Data Refresh SLA

The corpus index is refreshed **weekly (Monday 02:00 UTC)** via GitHub Actions.
Every response includes a `Last updated from sources: YYYY-MM-DD` footer indicating the index date.
Users should assume data may be up to 7 days old.

---

## Deployment

| Option | Backend | Frontend |
|---|---|---|
| **Recommended** | Render | Vercel |
| Self-hosted | Docker | Nginx static files |

---

## Disclaimer

> **Facts-only. No investment advice.**
> This assistant provides factual information about mutual fund schemes sourced exclusively from official Groww scheme pages. It does not provide investment advice, performance comparisons, return projections, or financial recommendations of any kind. Always consult a SEBI-registered investment advisor before making investment decisions.

---

*Version: 1.0.0 | AMC: HDFC Mutual Fund | Corpus: 5 Groww scheme URLs | LLM: Groq*
