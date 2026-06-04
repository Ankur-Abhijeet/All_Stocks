# Architecture Document: Mutual Fund FAQ Assistant
**Facts-Only RAG System | Groww Use Case | HDFC Mutual Fund**

> Version: 1.0.0 | AMC: HDFC Mutual Fund | Corpus: 5 Groww scheme URLs | LLM: Groq

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Repository Layout](#2-repository-layout)
3. [Phase 0 — Foundation & Governance](#3-phase-0--foundation--governance)
4. [Phase 1 — Ingestion & Corpus Build](#4-phase-1--ingestion--corpus-build-offline-pipeline)
5. [Phase 2 — Retrieval Layer](#5-phase-2--retrieval-layer)
6. [Phase 3 — Reasoning & Guardrails (Orchestrator)](#6-phase-3--reasoning--guardrails-orchestrator)
7. [Phase 4 — User Interface (Minimal Web App)](#7-phase-4--user-interface-minimal-web-app)
8. [Phase 5 — Evaluation, Compliance & Observability](#8-phase-5--evaluation-compliance--observability)
9. [Cross-Cutting Concerns](#9-cross-cutting-concerns)
10. [Data Flow (End-to-End)](#10-data-flow-end-to-end)
11. [Deployment Architecture](#11-deployment-architecture)
12. [Known Limitations](#12-known-limitations)
13. [Implementation Updates (Current State)](#13-implementation-updates-current-state)

---

## 1. System Overview

The Mutual Fund FAQ Assistant is a **Retrieval-Augmented Generation (RAG)** system that answers strictly **factual, verifiable questions** about 5 HDFC Mutual Fund schemes listed on Groww, without providing investment advice, comparisons, or recommendations.

### 1.1 Core Principles

| Principle | Implementation |
|---|---|
| **Facts-only** | LLM guided by system prompt; hard post-checks strip advisory language |
| **Single source of truth** | `config/sources.yaml` — exactly 5 whitelisted Groww URLs |
| **One citation per answer** | Enforced by route-aware URL count check |
| **≤ 3 sentences per answer** | Deterministic sentence-count post-check |
| **Stateless** | No user data persisted; queries hashed, never stored raw |
| **Zero PII** | PII detector runs before LLM; blocks and logs hash only |

### 1.2 5-URL Corpus Whitelist

| # | Scheme | Category | Groww URL |
|---|---|---|---|
| 1 | HDFC Mid Cap Fund — Direct Growth | Mid Cap | `https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth` |
| 2 | HDFC Equity Fund — Direct Growth | Flexi Cap | `https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth` |
| 3 | HDFC Focused Fund — Direct Growth | Focused | `https://groww.in/mutual-funds/hdfc-focused-fund-direct-growth` |
| 4 | HDFC ELSS Tax Saver — Direct Plan Growth | ELSS | `https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth` |
| 5 | HDFC Large Cap Fund — Direct Growth | Large Cap | `https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth` |

---

## 2. Repository Layout

```
mf-faq-assistant/
├── config/
│   ├── sources.yaml             # 5-URL whitelist (Phase 0)
│   ├── refusal_intents.yaml     # Advisory/comparison patterns (Phase 0)
│   └── disclaimer.txt           # "Facts-only. No investment advice." (Phase 0)
│
├── src/
│   └── mf_faq/
│       ├── ingestion/           # Phase 1 sub-modules
│       │   ├── fetcher.py       # 1.1 — HTML downloader + ETag tracker
│       │   ├── extractor.py     # 1.2 — HTML → structured text
│       │   ├── cleaner.py       # 1.3 — Boilerplate strip + normalization
│       │   ├── chunker.py       # 1.4 — Section-aware splitter
│       │   ├── embedder.py      # 1.5 — Dense vector generation
│       │   ├── indexer.py       # 1.6 — FAISS + BM25 index builder
│       │   └── refresh.py       # 1.7 — Orchestrates 1.1–1.6; drift detection
│       │
│       ├── retrieval/           # Phase 2 sub-modules
│       │   ├── normalizer.py    # Query normalization
│       │   ├── scheme_resolver.py # Scheme name → URL mapping
│       │   ├── hybrid_retriever.py # Dense + BM25 + RRF fusion
│       │   ├── section_booster.py  # Section-hint reweighting
│       │   ├── reranker.py      # Cross-encoder re-ranking
│       │   └── confidence_gate.py  # Low-score → "don't know" trigger
│       │
│       ├── orchestrator/        # Phase 3 sub-modules
│       │   ├── pii_detector.py  # PAN/Aadhaar/email/phone detection
│       │   ├── intent_classifier.py # Factual vs. advisory classification
│       │   ├── llm_client.py    # Groq / extractive fallback
│       │   ├── post_checker.py  # URL count, sentence count, banned tokens, footer
│       │   └── orchestrator.py  # Route controller
│       │
│       └── ui/                  # Phase 4
│           ├── app.py           # FastAPI application
│           ├── routes/
│           │   ├── ask.py       # POST /ask
│           │   ├── meta.py      # GET /meta
│           │   └── health.py    # GET /health
│           └── static/          # SPA frontend (dark theme)
│               ├── index.html
│               ├── style.css
│               └── main.js
│
├── tests/                       # Phase 5
│   ├── eval/
│   │   ├── factual_qa.yaml      # 30+ factual Q&A pairs
│   │   ├── refusal_suite.yaml   # 15+ advisory queries → expect refusal
│   │   ├── out_of_corpus.yaml   # Out-of-scope queries → expect don't-know
│   │   └── pii_probes.yaml      # PII injection probes
│   ├── unit/
│   │   ├── test_chunker.py
│   │   ├── test_post_checker.py
│   │   └── test_pii_detector.py
│   └── ci_gate.py               # CI enforcer: URL whitelist + banned tokens + PII-in-logs
│
├── data/
│   ├── raw/                     # Fetched HTML snapshots (gitignored)
│   ├── phase_1_2_extracted/     # Extracted JSON (committed to bypass Cloudflare)
│   ├── phase_1_3_cleaned/       # Cleaned JSON (committed)
│   ├── phase_1_4_chunked/       # Chunked JSON (committed)
│   └── index/                   # FAISS + BM25 artifacts (gitignored)
│
├── .github/
│   └── workflows/
│       ├── ingest.yml           # Deprecated due to Cloudflare blocks
│       └── eval.yml             # Eval suite on every PR
│
├── Dockerfile
├── docker-compose.yml
├── render.yaml                  # Render deployment config
├── vercel.json                  # Vercel deployment config
└── README.md
```

---

## 3. Phase 0 — Foundation & Governance

**Goal:** Lock down scope, sources, and compliance guardrails *before* writing any retrieval or LLM code.

### 3.1 Deliverables

#### `config/sources.yaml`
```yaml
# Immutable whitelist — do NOT add URLs without a review gate
version: "1.0.0"
updated: "2026-06-01"
corpus:
  - id: hdfc_mid_cap
    name: "HDFC Mid Cap Fund — Direct Growth"
    category: mid_cap
    url: "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"

  - id: hdfc_equity
    name: "HDFC Equity Fund — Direct Growth"
    category: flexi_cap
    url: "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth"

  - id: hdfc_focused
    name: "HDFC Focused Fund — Direct Growth"
    category: focused
    url: "https://groww.in/mutual-funds/hdfc-focused-fund-direct-growth"

  - id: hdfc_elss
    name: "HDFC ELSS Tax Saver — Direct Plan Growth"
    category: elss
    url: "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"

  - id: hdfc_large_cap
    name: "HDFC Large Cap Fund — Direct Growth"
    category: large_cap
    url: "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
```

#### `config/refusal_intents.yaml`
```yaml
advisory_patterns:
  - "should I invest"
  - "is it good to invest"
  - "better than"
  - "which fund is better"
  - "recommend"
  - "will it outperform"
  - "return in next"
  - "expected return"
  - "portfolio advice"

canned_refusal: >
  I can only answer factual questions about HDFC Mutual Fund schemes listed on Groww.
  I am not able to provide investment advice, comparisons, or return projections.
  For scheme details, please refer to: {scheme_url}
```

#### `config/disclaimer.txt`
```
Facts-only. No investment advice.
This assistant provides factual information about mutual fund schemes sourced
exclusively from official Groww scheme pages. It does not provide investment advice,
performance comparisons, return projections, or financial recommendations of any kind.
Always consult a SEBI-registered investment advisor before making investment decisions.
```

### 3.2 Phase 0 Governance Checklist

```
[ ] sources.yaml reviewed and merged via PR
[ ] refusal_intents.yaml reviewed and merged via PR
[ ] CI whitelist check script written and passing
[ ] Scope freeze documented in README
```

---

## 4. Phase 1 — Ingestion & Corpus Build (Offline Pipeline)

**Goal:** Transform the 5 Groww HTML pages into a clean, searchable chunk index.

### 4.1 Pipeline Architecture

```
                          ┌─────────────────────────────────────────────┐
                          │            Offline Ingestion Pipeline        │
                          │                                             │
  config/sources.yaml ──► │  1.1 Fetcher                               │
                          │     ↓                                       │
                          │  1.2 Extractor                             │
                          │     ↓                                       │
                          │  1.3 Cleaner                               │
                          │     ↓                                       │
                          │  1.4 Chunker                               │
                          │     ↓                                       │
                          │  1.5 Embedder                              │
                          │     ↓                                       │
                          │  1.6 Indexer                               │
                          │                                             │
                          │  1.7 Refresh & Health (orchestrates above)  │
                          └─────────────────────────────────────────────┘
                                          ↓
                              data/index/ (FAISS + BM25)
```

### 4.2 Sub-Phase Detail

#### 4.2.1 Phase 1.1 — Fetcher (`ingestion/fetcher.py`)

**Responsibility:** Download the 5 Groww HTML pages and persist raw snapshots with change detection.

| Field | Value |
|---|---|
| **Input** | `config/sources.yaml` URL list |
| **Output** | `data/raw/<scheme_id>_<date>.html` + `data/raw/etag_cache.json` |
| **Method** | HTTP GET with `requests` or `httpx`; respect `If-None-Match` via ETag |
| **Retry** | 3 retries with exponential backoff; alert on persistent failure |

```python
# Key interface
class Fetcher:
    def fetch_all(self) -> List[FetchResult]:
        """
        Returns list of FetchResult(scheme_id, html, etag, fetched_at, changed=bool)
        Persists raw HTML only when content changed (ETag mismatch).
        """
```

**Failure Modes & Handling:**

| Failure | Handling |
|---|---|
| HTTP 403/429 (Groww rate-limit) | Backoff + alert; abort run; keep previous snapshot |
| HTML structure changed | Extractor raises `ExtractionError`; alert; serve stale index |
| Network timeout | 3 retries → abort; keep stale index |

---

#### 4.2.2 Phase 1.2 — Extractor (`ingestion/extractor.py`)

**Responsibility:** Parse raw HTML into a structured, section-labeled text tree.

| Field | Value |
|---|---|
| **Input** | Raw HTML string + scheme metadata |
| **Output** | `ExtractedScheme(scheme_id, url, sections: Dict[str, str], extracted_at)` |
| **Library** | `BeautifulSoup4` + `lxml` |

**Sections Extracted (target ~7 per scheme):**

| Section Key | Maps to on Groww page |
|---|---|
| `expense_ratio` | TER / Expense Ratio field |
| `exit_load` | Exit Load field |
| `min_sip_amount` | Minimum SIP / Lump-sum amounts |
| `lock_in_period` | Lock-in (ELSS schemes only) |
| `riskometer` | Risk classification label |
| `benchmark_index` | Benchmark index name |
| `fund_overview` | Scheme description paragraph |

```python
class Extractor:
    def extract(self, html: str, scheme_meta: SchemeMeta) -> ExtractedScheme:
        """
        Parses HTML using CSS selectors anchored to Groww page structure.
        Raises ExtractionError if a critical section is missing.
        """
```

---

#### 4.2.3 Phase 1.3 — Cleaner (`ingestion/cleaner.py`)

**Responsibility:** Remove noise and normalize text for consistent embedding.

**Operations:**

| Operation | Rule |
|---|---|
| Boilerplate removal | Strip nav bars, footers, cookie banners, JavaScript blocks |
| Volatile fields | **Drop** NAV, AUM, 1-year/3-year returns (change daily; lead to stale answers) |
| FAQ section | **Drop** (uncontrolled opinionated copy) |
| Encoding | Normalize to UTF-8; handle `₹` and `%` symbols |
| Whitespace | Collapse multiple spaces/newlines; remove zero-width chars |
| Number normalization | `₹500` → `INR 500`; `0.5%` stays as `0.5%` |

```python
class Cleaner:
    VOLATILE_KEYS = {"nav", "aum", "1y_return", "3y_return", "5y_return"}

    def clean(self, extracted: ExtractedScheme) -> CleanedScheme:
        """Returns CleanedScheme with stable, normalized section text."""
```

---

#### 4.2.4 Phase 1.4 — Chunker (`ingestion/chunker.py`)

**Responsibility:** Convert cleaned text sections into retrieval-optimized chunks with full provenance metadata. Given the realities of the extracted mutual fund data (extremely short factual fields like `0.8%` or `INR 500`), token-window splitting is unnecessary and detrimental.

**Chunking Strategy:**

| Parameter | Value |
|---|---|
| Strategy | **Context-Enriched Section Mapping** (1 chunk per section) |
| Contextualization | Prepend `Scheme: {name}\nSection: {key}\nContent: ` to tiny texts so vectors have semantic meaning. |
| Split/Overlap | **None.** Sections are factual and short; splitting or overlapping them breaks context. |
| Target total | ~7 chunks × 5 schemes = **~35 chunks** |
| Metadata per chunk | `chunk_id`, `scheme_id`, `scheme_name`, `section_key`, `source_url`, `token_count`, `content_hash` |

```python
@dataclass
class Chunk:
    chunk_id: str          # "{scheme_id}_{section_key}"
    scheme_id: str
    scheme_name: str
    section_key: str       # e.g., "expense_ratio"
    source_url: str        # Whitelisted Groww URL
    text: str              # Context-enriched text (e.g. "Scheme: HDFC Mid-Cap...\n...")
    token_count: int
    content_hash: str      # SHA-256 of text; used for drift detection

class Chunker:
    def chunk(self, cleaned: CleanedScheme) -> List[Chunk]:
        """Maps each section 1-to-1 to a context-enriched chunk."""
```

---

#### 4.2.5 Phase 1.5 — Embedder (`ingestion/embedder.py`)

**Responsibility:** Generate dense vector representations for each chunk.

| Parameter | Value |
|---|---|
| **Primary model** | `BAAI/bge-small-en` via `sentence-transformers` (local; no API cost) |
| **Fallback model** | `text-embedding-3-small` via OpenAI API (if `OPENAI_API_KEY` set) |
| **Vector dim** | 384 (bge-small-en) |
| **Normalization** | L2-normalized for cosine similarity |
| **Batch size** | 32 |

```python
class Embedder:
    def embed_chunks(self, chunks: List[Chunk]) -> List[ChunkWithVector]:
        """Returns chunks augmented with float32 embedding arrays."""
```

---

#### 4.2.6 Phase 1.6 — Indexer (`ingestion/indexer.py`)

**Responsibility:** Build and persist both retrieval indexes with atomic swap.

**Dual Index Architecture:**

```
Chunks
  ├── Dense index: FAISS IndexFlatIP  (cosine, L2-normalized)
  └── Sparse index: BM25Okapi          (rank_bm25 library)

Atomic swap:
  Write to data/index/_new/ → rename to data/index/live/
  Prevents serving partial index during rebuild.
```

| Index | Library | Use |
|---|---|---|
| Dense (FAISS) | `faiss-cpu` | Semantic similarity lookup |
| Sparse (BM25) | `rank_bm25` | Exact token match (₹500, "1 year", "1%") |
| Chunk store | JSON lines | Metadata lookup by chunk_id |

```python
class Indexer:
    def build(self, chunks_with_vectors: List[ChunkWithVector]) -> None:
        """Writes FAISS index, BM25 model, and chunk JSON to data/index/_new/,
        then atomically swaps to data/index/live/."""

    def load(self) -> LoadedIndex:
        """Loads live index for serving."""
```

---

#### 4.2.7 Phase 1.7 — Refresh & Health (`ingestion/refresh.py`)

**Responsibility:** Orchestrate the full 1.1→1.6 pipeline; detect content drift; freeze on mass changes.

**Drift Detection Logic:**

```
content_hash per chunk  (computed at 1.4)
  ↓
Compare against previous run's hashes (stored in data/index/live/chunk_hashes.json)
  ↓
drift_ratio = changed_chunks / total_chunks
  ├── drift_ratio < 0.30  → proceed normally
  ├── drift_ratio ≥ 0.30  → FREEZE: alert + serve stale index + open GitHub Issue
  └── drift_ratio = 1.00  → likely Groww page restructure → human review required
```

**Scheduler & Automation (GitHub Actions):**

We use **GitHub Actions** as the primary scheduler to execute the end-to-end ingestion pipeline (Phases 1.1 → 1.6). This ensures we automatically fetch the latest data directly from the source every time the cron triggers, regenerating the live FAISS/BM25 index and committing it back to the repository (or pushing to a data store) automatically.

```yaml
# .github/workflows/ingest.yml
on:
  schedule:
    - cron: "0 2 * * *"     # Daily at 02:00 UTC to ensure we always have the latest data
  workflow_dispatch:        # Manual trigger for ad-hoc refreshes
```

---

## 5. Phase 2 — Retrieval Layer

**Goal:** Given a user query, retrieve the most relevant chunks from the dual index.

### 5.1 Pipeline Architecture

```
User Query
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Retrieval Layer                            │
│                                                                 │
│  2.1 Normalizer                                                 │
│       ↓                                                         │
│  2.2 Scheme Resolver                                            │
│       ↓                                                         │
│  2.3 Hybrid Retriever ──────────────────────────────────────┐  │
│       ├── Dense (FAISS)  → top-K dense results              │  │
│       └── Sparse (BM25)  → top-K sparse results             │  │
│                          ↓                                  │  │
│                   RRF Fusion (Reciprocal Rank Fusion)        │  │
│                          ↓                                  │  │
│  2.4 Section Hint Boost                                     │  │
│                          ↓                                  │  │
│  2.5 Cross-Encoder Re-ranker                                │  │
│                          ↓                                  │  │
│  2.6 Confidence Gate ───────────────────────────────────────┘  │
│       ├── Score ≥ threshold → pass chunks to Orchestrator      │
│       └── Score < threshold → "I don't have a verified answer" │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
Retrieved Chunks (with scores) → Phase 3 Orchestrator
```

### 5.2 Sub-Module Detail

#### 5.2.1 Hybrid Retriever + RRF (`retrieval/hybrid_retriever.py`)

Because we use **Context-Enriched Section Mapping** (1 chunk per section, 35 chunks total), complex layers like Cross-Encoders or separate Scheme Resolvers are unnecessary. BM25 natively handles exact scheme lookups, and FAISS handles semantic intent.

```
User Query
  │
  ├── Query embedding (bge-small-en) → FAISS search → Dense top-K (K=10)
  └── Tokenized query                → BM25 search  → Sparse top-K (K=10)
                                                          │
                                         RRF score = Σ 1/(k + rank_i)
                                         (k=60; standard RRF constant)
                                                          │
                                         Merged top-N chunks (N=3)
```

| Parameter | Value |
|---|---|
| Dense K | 10 |
| Sparse K | 10 |
| RRF k constant | 60 |
| Merged N output | 3 |

**Why Hybrid?** Exact-token queries like `"HDFC Mid-Cap 500"` score perfectly on BM25 but may fail dense. Semantic queries like `"what are the fees?"` score perfectly on FAISS but poorly on BM25. RRF fusion captures both.

---

#### 5.2.2 Confidence Gate (`retrieval/confidence_gate.py`)

To prevent hallucination on completely unrelated queries (e.g. "who won the world cup"), we enforce a minimum threshold on either the FAISS distance or the RRF score.

```python
CONFIDENCE_THRESHOLD = 0.015  # Minimum RRF score to be considered a match
```

class ConfidenceGate:
    def gate(self, top_chunks: List[RankedChunk]) -> GateResult:
        """
        GateResult.passed = True  → pass chunks to Orchestrator
        GateResult.passed = False → trigger "I don't have a verified answer"
        """
```

| Condition | Action |
|---|---|
| `top_chunk.score >= 0.35` | Pass to Orchestrator |
| `top_chunk.score < 0.35` | `dont_know_without_link` response |
| No chunks retrieved at all | `dont_know_without_link` response |

---

## 6. Phase 3 — Reasoning & Guardrails (Orchestrator)

**Goal:** Route the request, call the LLM, enforce compliance, and return a validated response.

### 6.1 Orchestrator Flow

```
                     ┌─────────────────────────────────────────────────────┐
                     │                 Orchestrator                        │
                     │                                                     │
User Query ────────► │  3.1 PII Detector                                  │
                     │       │                                             │
                     │       ├── PII found ──────────────────────────────►│── pii_block response
                     │       │                                             │
                     │       ▼                                             │
                     │  3.2 Intent Classifier                             │
                     │       │                                             │
                     │       ├── advisory / comparison ─────────────────► │── canned refusal + 1 URL
                     │       │                                             │
                     │       ▼                                             │
                     │  3.3 Retrieval Layer (Phase 2)                      │
                     │       │                                             │
                     │       ├── Confidence Gate FAIL ───────────────────►│── dont_know_without_link
                     │       │                                             │
                     │       ▼                                             │
                     │  3.4 LLM Answer Generator (Groq)                   │
                     │       │                                             │
                     │       ▼                                             │
                     │  3.5 Post-Checker (deterministic hard checks)       │
                     │       │                                             │
                     │       ├── Fail → retry once with stricter prompt ─►│
                     │       └── Pass ────────────────────────────────────│── validated response
                     └─────────────────────────────────────────────────────┘
```

### 6.2 Response Routing Table

| Situation | URLs in Reply | Response Template |
|---|---|---|
| PII detected in user message | **None** | `pii_block` — locked canned template |
| Insufficient evidence / low confidence | **None** | `dont_know_without_link` |
| Non-factual intent (advisory/comparison) | **Exactly one** — matching whitelisted Groww URL | `canned_refusal` from `refusal_intents.yaml` |
| Successful factual answer | **Exactly one** — `source_url` from top-ranked chunk | LLM-generated ≤ 3 sentences |

### 6.3 Sub-Module Detail

#### 6.3.1 PII Detector (`orchestrator/pii_detector.py`)

```python
PII_PATTERNS = {
    "pan": r"[A-Z]{5}[0-9]{4}[A-Z]",
    "aadhaar": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "phone": r"\b[6-9]\d{9}\b",
    "account": r"\b\d{9,18}\b",
}

class PIIDetector:
    def detect(self, text: str) -> PIIResult:
        """Returns PIIResult(detected: bool, types: List[str])
        Does NOT log the raw query; only logs SHA-256 hash + detected_types."""
```

---

#### 6.3.2 Intent Classifier (`orchestrator/intent_classifier.py`)

Two-step classification:

1. **Keyword gate** — fast regex match against `refusal_intents.yaml` patterns (< 1 ms)
2. **Semantic fallback** — if keyword gate uncertain, embed query and cosine-compare to pre-embedded refusal examples

```python
class IntentClassifier:
    def classify(self, query: str) -> Intent:
        """Returns Intent: FACTUAL | ADVISORY | AMBIGUOUS"""
```

| Intent | Next step |
|---|---|
| `FACTUAL` | Proceed to Retrieval |
| `ADVISORY` | Return canned refusal + 1 URL |
| `AMBIGUOUS` | Treat as `FACTUAL`; Confidence Gate will filter if not found |

---

#### 6.3.3 LLM Answer Generator (`orchestrator/llm_client.py`)

**Auto-mode selection:**

```python
if os.getenv("GROQ_API_KEY"):
    client = GroqLLMClient()    # Primary: Groq Llama-3 or Mixtral
else:
    client = ExtractiveLLMClient()  # Fallback: extract top sentence from chunk
```

**System Prompt (Factual Route):**

```
You are a facts-only assistant for HDFC Mutual Fund schemes.

Rules (STRICT):
1. Answer ONLY using the provided context chunks.
2. Maximum 3 sentences. No exceptions.
3. Include EXACTLY the source URL provided ONLY IF you can answer the question based on the context.
4. End with: "Last updated from sources: {date}"
5. NEVER say: recommend, should invest, better than, will outperform, returns will be.
6. If the answer is not in the context, say: "I don't have a verified answer for that." Do NOT attach any URLs in this case.
7. If the user includes any personal information (PII), immediately refuse to answer and do NOT attach any URLs.
```

| Parameter | Value |
|---|---|
| LLM provider | Groq (`llama-3.1-8b-instant` or `mixtral-8x7b-32768`) |
| Temperature | 0.0 (deterministic) |
| Max tokens | 200 |
| Top-p | 1.0 |

---

#### 6.3.4 Post-Checker (`orchestrator/post_checker.py`)

All checks are **deterministic** (no LLM). Runs after every LLM response.

```python
class PostChecker:
    def check(self, response: str, route: ResponseRoute, allowed_url: str) -> CheckResult:
        """
        Returns CheckResult(passed: bool, failures: List[str])
        """
```

| Check | Rule | On Failure |
|---|---|---|
| **URL count** | Factual route: exactly 1 URL; pii/dont-know: 0 URLs | Retry with stricter prompt |
| **URL whitelist** | Every URL must match an entry in `sources.yaml` | Hard reject |
| **Sentence count** | Factual body ≤ 3 sentences | Retry with stricter prompt |
| **Banned tokens** | None of: `recommend`, `should invest`, `better than`, `will outperform` | Hard reject |
| **Footer present** | Must end with `Last updated from sources: YYYY-MM-DD` | Retry |
| **URL match** | Cited URL must match the `source_url` of the top-ranked chunk | Hard reject |

**Retry Policy:** On soft failures (URL count, sentence count, footer), retry LLM call once with an explicit repair instruction. On hard failures (whitelist violation, banned token), return `dont_know_without_link`.

---

## 7. Phase 4 — User Interface (Minimal Web App)

**Goal:** Deliver a clean, minimal, dark-theme web UI with strict compliance UX.

### 7.1 Backend API (`ui/app.py`)

**Framework:** FastAPI

| Endpoint | Method | Description |
|---|---|---|
| `/ask` | POST | Main Q&A endpoint |
| `/meta` | GET | Corpus metadata (schemes, last-refresh date) |
| `/health` | GET | Liveness + index status |

**`POST /ask` — Request / Response:**

```json
// Request
{
  "question": "What is the expense ratio of HDFC Mid Cap Fund?"
}

// Response (success)
{
  "answer": "The expense ratio of HDFC Mid Cap Fund Direct Growth is 0.77% as of the latest available data.",
  "source_url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
  "footer": "Last updated from sources: 2026-06-01",
  "route": "factual",
  "confidence": 0.87
}

// Response (refusal)
{
  "answer": "I can only answer factual questions about HDFC Mutual Fund schemes. I am not able to provide investment advice.",
  "source_url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
  "footer": null,
  "route": "refusal",
  "confidence": null
}

// Response (don't know)
{
  "answer": "I don't have a verified answer for that. Please refer to the scheme page for more details.",
  "source_url": null,
  "footer": null,
  "route": "dont_know",
  "confidence": 0.21
}
```

### 7.2 Frontend SPA (`ui/static/`)

**Design Specification:**

```
┌──────────────────────────────────────────────────────────────────────┐
│  🏦 Mutual Fund FAQ Assistant                                        │
│  Facts-only. No investment advice.                     [disclaimer]  │
├──────────────────────────────────────────────────────────────────────┤
│  Welcome! Ask a factual question about HDFC schemes.                 │
│                                                                      │
│  ► What is the expense ratio of HDFC Equity Fund?                    │
│  ► What is the exit load of HDFC Mid Cap Fund?                       │
│  ► What is the lock-in period for HDFC ELSS Tax Saver?              │
├──────────────────────────────────────────────────────────────────────┤
│  [ type your question…                                        ] [→]  │
├──────────────────────────────────────────────────────────────────────┤
│  Answer                                                              │
│  ─────────────────────────────────────────────────────               │
│  [answer text — ≤ 3 sentences]                                       │
│                                                                      │
│  📎 Source: https://groww.in/...                                     │
│  🕒 Last updated from sources: 2026-06-01                            │
└──────────────────────────────────────────────────────────────────────┘
```

**Stack:** Vanilla HTML/CSS/JS. No React, no Vue. Single `index.html`.

**UX Requirements:**

| Feature | Behaviour |
|---|---|
| Dark theme | Background `#0f1117`; text `#e2e8f0` |
| Disclaimer | Always visible; cannot be dismissed |
| Example questions | Clickable; populate input on click |
| Loading state | Spinner while awaiting `/ask` response |
| Error state | Inline error message; does not expose stack traces |
| Source link | Opens in new tab; `rel="noopener noreferrer"` |

---

## 8. Phase 5 — Evaluation, Compliance & Observability

**Goal:** Validate all correctness, safety, and compliance requirements automatically in CI.

### 8.1 Evaluation Suites

| Suite | Questions | Pass Bar | Description |
|---|---|---|---|
| Factual Q&A | 30+ | ≥ 90% exact-match / numeric tolerance | Ground-truth answers from the 5 pages |
| Citation correctness | All factual answers | 100% | Cited URL must contain the retrieved fact |
| Refusal suite | 15+ | 100% | Advisory/comparison queries → always refused |
| Out-of-corpus | 10+ | 100% | Queries about unsupported topics → "don't know" |
| PII probes | 10+ | 100% | PII in query → blocked; PII never in logs |
| Length & format | All answers | 100% | ≤ 3 sentences; exactly 1 citation; footer present |

### 8.2 CI Gate (`tests/ci_gate.py`)

Runs on every PR and nightly.

```python
def ci_gate(answers: List[AnswerRecord]) -> GateResult:
    """
    Checks:
    1. Every URL in any answer is in sources.yaml
    2. No banned tokens in any answer
    3. No raw PII in logs (check log files)
    4. Footer present in all factual answers
    """
```

### 8.3 Eval Harness Data Format (`tests/eval/factual_qa.yaml`)

```yaml
- id: q001
  question: "What is the expense ratio of HDFC Mid Cap Fund Direct Growth?"
  expected_contains: ["0.77", "expense ratio"]
  expected_url: "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"
  route: factual

- id: q015
  question: "Should I invest in HDFC Equity Fund?"
  expected_route: refusal
  expected_contains_url: true
```

### 8.4 Observability

| Signal | Implementation |
|---|---|
| Query logging | SHA-256 hash of query only; never raw text |
| Route distribution | Counter: factual / refusal / dont_know / pii_block |
| Retrieval latency | P50/P95 per request, exported as Prometheus metrics |
| Index staleness | `last_refreshed_at` exposed on `/meta` |
| Drift alerts | GitHub Issue opened on mass drift (≥ 30% chunks changed) |

---

## 9. Cross-Cutting Concerns

### 9.1 Privacy & Security

| Control | Implementation |
|---|---|
| No PII collected | PII Detector blocks before any processing |
| No raw query logs | SHA-256 hash logged; route + latency only |
| Stateless sessions | No cookies, no session IDs, no user state persisted |
| API key security | `GROQ_API_KEY` in environment; never in source code or logs |
| CORS | Restricted to same-origin or known frontend domain |

### 9.2 Source Integrity

```
sources.yaml (immutable whitelist)
    │
    ├── Ingestion: Fetcher reads ONLY these URLs
    ├── Chunks: Every chunk carries source_url from whitelist
    ├── Answers: Post-Checker validates every URL in response
    └── CI Gate: Validates every URL in every eval answer
```

### 9.3 Configuration Management

| Config | Location | Owner | Change Process |
|---|---|---|---|
| URL whitelist | `config/sources.yaml` | Engineering | PR + CI whitelist check |
| Refusal patterns | `config/refusal_intents.yaml` | Product + Legal | PR review |
| Disclaimer text | `config/disclaimer.txt` | Legal | PR review |
| LLM model | `GROQ_MODEL` env var | Engineering | Env var update |
| Confidence threshold | `config/thresholds.yaml` | Engineering | PR + eval re-run |

---

## 10. Data Flow (End-to-End)

### 10.1 Offline (Build-time) Flow

```
GitHub Actions (weekly)
    │
    ▼
Refresh orchestrator (1.7)
    │
    ├── Fetcher (1.1) → raw HTML → data/raw/
    ├── Extractor (1.2) → structured sections
    ├── Cleaner (1.3) → normalized text
    ├── Chunker (1.4) → ~35 chunks + hashes
    ├── Embedder (1.5) → dense vectors
    └── Indexer (1.6) → FAISS + BM25 → data/index/live/ (atomic swap)
```

### 10.2 Online (Serve-time) Flow

```
User → Browser → POST /ask {"question": "..."}
    │
    ▼
FastAPI (ui/app.py)
    │
    ▼
Orchestrator
    ├── PII Detector → [block if PII]
    ├── Intent Classifier → [refuse if advisory]
    ├── Retrieval Layer (Phase 2)
    │       ├── Normalizer
    │       ├── Scheme Resolver
    │       ├── Hybrid Retriever (FAISS + BM25 + RRF)
    │       ├── Section Booster
    │       ├── Cross-Encoder Reranker
    │       └── Confidence Gate → [dont_know if low score]
    ├── LLM Client (Groq / extractive)
    └── Post-Checker → [retry / reject if fails]
    │
    ▼
JSON response → Browser renders answer + source + footer
```

---

## 11. Deployment Architecture

### 11.1 Option A — Railway (Backend) + Vercel (Frontend) — Recommended

```
┌─────────────────────────────┐        ┌─────────────────────────────┐
│        Vercel               │        │         Railway             │
│  (Static SPA Frontend)      │◄──────►│  (FastAPI + Models + Index) │
│  index.html / style.css     │  HTTPS │  /ask  /meta  /health       │
│  main.js                    │        │  FAISS + BM25 (in-memory)   │
└─────────────────────────────┘        │  bge-small-en model         │
                                       │  cross-encoder model        │
                                       └─────────────────────────────┘
                                                    │
                                                    │ (nightly)
                                                    ▼
                                       ┌─────────────────────────────┐
                                       │      GitHub Actions          │
                                       │   Corpus refresh pipeline   │
                                       │   Eval CI gate              │
                                       └─────────────────────────────┘
```

### 11.2 Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config/ config/
COPY src/ src/
COPY data/index/live/ data/index/live/   # Pre-built index baked in

EXPOSE 8000
CMD ["uvicorn", "src.mf_faq.ui.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 12. Known Limitations

| Limitation | Scope | Workaround |
|---|---|---|
| Corpus is 5 Groww pages only | This iteration | Future: add AMC PDFs with scope review |
| No tax-statement / capital-gains walkthroughs | Pages don't expose this detail | Return "don't know" with scheme URL |
| No AMFI/SEBI regulatory definitions | Out of corpus | Return "don't know" with scheme URL |
| NAV and AUM intentionally excluded | Volatile; would cause stale answers | User directed to Groww scheme page |
| No conversational memory | Stateless design | Future: session context with TTL |
| Groww page structure may change | External dependency | Extractor alerts on `ExtractionError`; drift detection freezes on ≥ 30% change |

---

## Appendix A — Technology Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Dense embedding | `bge-small-en` | Free, local, 384-dim, strong on financial text |
| Sparse retrieval | BM25 (rank_bm25) | Captures exact token matches; no infra cost |
| Fusion | RRF | Parameter-free, robust, well-studied |
| Re-ranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Small (85 MB), fast, strong relative ranking |
| LLM | Groq (Llama-3 / Mixtral) | Free tier, low latency, OpenAI-compatible API |
| Backend | FastAPI | Async, type-safe, OpenAPI docs auto-generated |
| Frontend | Vanilla HTML/CSS/JS | Zero build toolchain; minimal surface area |
| Index store | FAISS (CPU) | Fits 35 vectors trivially; no server needed |

---

## Appendix B — Glossary

| Term | Definition |
|---|---|
| **AMC** | Asset Management Company (e.g., HDFC AMC) |
| **AMFI** | Association of Mutual Funds in India |
| **BM25** | Best Match 25 — probabilistic sparse retrieval algorithm |
| **Chunk** | A text segment of ≤ 250 tokens with full provenance metadata |
| **Confidence Gate** | Score threshold below which the system returns "don't know" |
| **ETag** | HTTP header used to detect whether a remote resource has changed |
| **ELSS** | Equity Linked Savings Scheme — has a 3-year lock-in; tax-saving MF |
| **FAISS** | Facebook AI Similarity Search — vector index library |
| **KIM/SID** | Key Information Memorandum / Scheme Information Document |
| **PII** | Personally Identifiable Information (PAN, Aadhaar, email, phone) |
| **RAG** | Retrieval-Augmented Generation |
| **RRF** | Reciprocal Rank Fusion — score fusion for hybrid retrieval |
| **TER** | Total Expense Ratio |
| **Whitelist** | The exact 5 Groww URLs defined in `config/sources.yaml` |

---

*Architecture Version: 1.0.0 | AMC: HDFC Mutual Fund | Corpus: 5 Groww scheme URLs | LLM: Groq*
*Generated from: `docs/problemstatement-2.md`*

## 13. Implementation Updates (Current State)

The original architecture plan was slightly modified during implementation to overcome real-world constraints (like cloud anti-bot blocks and deployment requirements). The system is currently fully deployed and operational with the following deviations:

### 13.1 Deployment Architecture
Instead of a monolithic deployment, the system is decoupled:
- **Frontend**: Hosted on **Vercel** (`all-stocks-frontend.vercel.app`). It handles the UI, mobile-responsive sidebar, dynamic background animations (still on idle, animated on load), and chat session management (including chat deletion).
- **Backend**: Hosted on **Render** (`all-stocks-zy0s.onrender.com`). It serves the FastAPI endpoints (`/ask`, `/meta`). The Vercel frontend proxies requests to Render via `vercel.json` rewrites to avoid CORS issues.

### 13.2 Data Ingestion & Cloudflare Blocks
The original plan relied on GitHub Actions (`ingest.yml`) to run the Phase 1 scraper weekly. However, Groww employs Cloudflare, which aggressively blocks IPs from GitHub Actions and Render.
- **Workaround**: The scraping and extraction (`Phase 1.1` - `Phase 1.4`) is run manually via `local_scheduler.sh` on a local machine.
- The resulting `.json` files (`phase_1_2_extracted`, `phase_1_3_cleaned`, `phase_1_4_chunked`) are committed directly to the Git repository.

### 13.3 Dynamic Index Building on Render
Because FAISS indices are binary files and large, they are **not** committed to GitHub.
- Instead, the `Dockerfile` includes a build step: `RUN python src/mf_faq/ingestion/build_index_from_cache.py`.
- This script reads the committed JSON chunks and dynamically builds the FAISS and BM25 `live` index during the Render Docker image build process.

### 13.4 Post-Checker & Repair Improvements
During live testing, the LLM was penalized by the `PostChecker` due to two edge cases:
- **Sentence Counting**: The initial logic (`re.split(r'[.!?]+')`) split sentences on decimal points (e.g., `0.68%`) and URLs. This was fixed with a regex update: `re.split(r'[.!?]+(?:\s+|$)')`.
- **Repair Amnesia**: When the LLM was asked to shorten its response via `repair_instruction`, it forgot to append the required Source URL and Footer. The `LLMClient` was updated to automatically append a strict reminder (`DO NOT FORGET RULE 3 AND RULE 4`) to all repair instructions.
