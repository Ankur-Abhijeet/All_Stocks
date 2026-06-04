"""
src/mf_faq/ui/app.py
=====================
Phase 4 — Backend API using FastAPI.

Exposes the Orchestrator via REST endpoints.
"""

from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
from datetime import date

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from mf_faq.orchestrator.orchestrator import Orchestrator
from mf_faq.config.loader import load_config


# Global orchestrator instance
orchestrator: Optional[Orchestrator] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager to load the orchestrator exactly once on startup."""
    global orchestrator
    orchestrator = Orchestrator()
    yield
    # Cleanup on shutdown if necessary
    orchestrator = None


app = FastAPI(title="HDFC Mutual Fund FAQ Assistant", lifespan=lifespan)

# Add CORS middleware to allow the frontend to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str
    history: Optional[list] = None


class AskResponse(BaseModel):
    answer: str
    source_url: Optional[str]
    footer: Optional[str]
    route: str
    confidence: Optional[float]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized.")

    raw_result = orchestrator.ask(req.question, history=req.history)
    raw_answer = raw_result["answer"]
    source_url = raw_result["source_url"]

    # Parse route
    # Note: Phase 3 currently just returns raw_result with 'answer' and 'source_url'
    # Let's derive route based on response string
    if orchestrator.PII_BLOCK_RESPONSE in raw_answer:
        route = "refusal"
    elif any(r in raw_answer for r in [
        orchestrator.DONT_KNOW_RESPONSE, 
        orchestrator.RETRIEVAL_FAILURE_RESPONSE, 
        orchestrator.HARD_REJECT_RESPONSE, 
        orchestrator.SOFT_FAIL_RESPONSE
    ]):
        route = "dont_know"
    elif orchestrator.CANNED_REFUSAL_RESPONSE in raw_answer:
        route = "refusal"
    else:
        route = "factual"

    # Separate footer from answer body for factual responses
    footer = None
    answer_body = raw_answer
    
    # Check if "Last updated from sources" is in the answer
    footer_start = "Last updated from sources:"
    if footer_start in raw_answer:
        parts = raw_answer.split(footer_start)
        # The body is everything before the footer (stripped of trailing newlines)
        answer_body = parts[0].strip()
        # The footer is the footer string itself + the date
        footer = footer_start + parts[1].split("\n")[0]
        
    # Also strip out the Source URL line if the LLM injected it verbatim 
    # instead of just relying on the JSON 'source_url' field.
    # The architecture states the output is just max 3 sentences of factual text.
    if "Source URL:" in answer_body:
        answer_body = answer_body.split("Source URL:")[0].strip()

    return AskResponse(
        answer=answer_body,
        source_url=source_url,
        footer=footer,
        route=route,
        # Our context-enriched design bypassed cross-encoder, so we don't calculate a raw 0-1 float.
        # Returning null for now, or a dummy confidence to satisfy the JSON interface.
        confidence=0.99 if route == "factual" else None
    )


@app.get("/meta")
def meta() -> Dict[str, Any]:
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized.")
        
    cfg = orchestrator.app_cfg
    schemes = [
        {"id": s.id, "name": s.name, "url": s.url}
        for s in cfg.sources.corpus
    ]
    return {
        "amc": cfg.sources.amc,
        "schemes": schemes,
        "last_updated": str(date.today()), # In a real app, read timestamp from data/raw/etag_cache.json
        "disclaimer": cfg.disclaimer
    }


@app.get("/health")
def health() -> Dict[str, str]:
    if not orchestrator:
        return {"status": "starting up or degraded"}
    return {"status": "ok", "index_loaded": str(orchestrator.retriever.index.chunk_count > 0)}

# API-only mode: static files have been moved to the frontend/ directory
# for independent Vercel deployment.

