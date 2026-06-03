"""
src/mf_faq/config/loader.py
============================
Phase 0 — Configuration Loader & Validator

Loads and validates all config files at application startup.
Any misconfiguration raises a ConfigurationError immediately so the
application never boots in a broken state.

Validated files:
  - config/sources.yaml        (URL whitelist)
  - config/refusal_intents.yaml (refusal patterns + canned copy)
  - config/disclaimer.txt       (disclaimer text)
  - config/thresholds.yaml      (tunable numeric parameters)

Usage:
    from mf_faq.config.loader import load_config
    cfg = load_config()          # Call once at startup
    print(cfg.sources.corpus)    # Access validated config objects
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_DOMAIN = "https://groww.in/mutual-funds/"
REQUIRED_CORPUS_COUNT = 5
MIN_REFUSAL_PATTERNS = 5
MIN_ADVISORY_EXAMPLES = 5
REQUIRED_PLACEHOLDER = "{scheme_url}"

# Resolve config directory relative to project root.
# Supports both local dev (running from project root) and Docker deployments.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # src/mf_faq/config -> project root
CONFIG_DIR = _PROJECT_ROOT / "config"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfigurationError(Exception):
    """Raised when a config file is missing, malformed, or violates a rule."""


# ---------------------------------------------------------------------------
# Data classes — typed representations of each config file
# ---------------------------------------------------------------------------


@dataclass
class SchemeConfig:
    id: str
    name: str
    category: str
    url: str
    sections_required: List[str]
    sections_optional: List[str]


@dataclass
class SourcesConfig:
    version: str
    updated: str
    amc: str
    allowed_domain: str
    corpus: List[SchemeConfig]

    @property
    def urls(self) -> List[str]:
        return [s.url for s in self.corpus]

    @property
    def url_to_scheme(self) -> Dict[str, SchemeConfig]:
        return {s.url: s for s in self.corpus}

    @property
    def id_to_scheme(self) -> Dict[str, SchemeConfig]:
        return {s.id: s for s in self.corpus}


@dataclass
class RefusalConfig:
    version: str
    updated: str
    advisory_patterns: List[str]
    advisory_semantic_examples: List[str]
    canned_refusal: str
    pii_block: str
    dont_know_without_link: str
    empty_query: str


@dataclass
class ThresholdsConfig:
    # Retrieval
    dense_top_k: int
    sparse_top_k: int
    rrf_k: int
    rrf_merged_n: int
    section_boost_factor: float
    reranker_input_n: int
    reranker_output_n: int
    # Confidence
    factual_threshold: float
    ambiguous_threshold: float
    # Chunking
    token_soft_cap: int
    token_overlap: int
    min_expected_chunks: int
    min_chunk_text_length: int
    # Fetching
    request_timeout_seconds: int
    max_retries: int
    retry_base_delay_seconds: int
    min_content_bytes: int
    # Drift
    freeze_threshold: float
    raw_snapshots_keep_last: int
    # LLM
    max_tokens: int
    temperature: float
    max_soft_retries: int
    # API
    max_question_length: int
    max_concurrent_requests: int
    ask_timeout_seconds: int


@dataclass
class AppConfig:
    sources: SourcesConfig
    refusal: RefusalConfig
    thresholds: ThresholdsConfig
    disclaimer: str
    config_hash: str  # SHA-256 of the concatenated raw YAML bytes (for cache busting)


# ---------------------------------------------------------------------------
# Internal loaders
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    """Load a YAML file, raising ConfigurationError on parse failure."""
    if not path.exists():
        raise ConfigurationError(f"Required config file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if data is None:
            raise ConfigurationError(f"Config file is empty: {path}")
        return data
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"YAML parse error in {path}: {exc}") from exc


def _load_text(path: Path) -> str:
    """Load a plain-text file, raising ConfigurationError if missing or empty."""
    if not path.exists():
        raise ConfigurationError(f"Required config file not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ConfigurationError(f"Config file is empty: {path}")
    return text


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _validate_sources(data: dict, path: Path) -> SourcesConfig:
    """Validate sources.yaml against all Phase 0 + edge-case rules."""

    # Required top-level keys
    for key in ("version", "updated", "amc", "allowed_domain", "corpus"):
        if key not in data:
            raise ConfigurationError(f"sources.yaml missing required key: '{key}'")

    corpus_raw = data["corpus"]
    if not isinstance(corpus_raw, list):
        raise ConfigurationError("sources.yaml: 'corpus' must be a list.")

    # EC-P0-005: Exact corpus count check
    if len(corpus_raw) != REQUIRED_CORPUS_COUNT:
        raise ConfigurationError(
            f"sources.yaml must contain exactly {REQUIRED_CORPUS_COUNT} corpus entries; "
            f"found {len(corpus_raw)}."
        )

    seen_urls: set = set()
    seen_ids: set = set()
    schemes: List[SchemeConfig] = []

    for idx, entry in enumerate(corpus_raw):
        for key in ("id", "name", "category", "url", "sections_required"):
            if key not in entry:
                raise ConfigurationError(
                    f"sources.yaml corpus[{idx}] missing required field: '{key}'"
                )

        url: str = entry["url"]
        scheme_id: str = entry["id"]

        # EC-P0-001: URL must be on the allowed domain
        if not url.startswith(ALLOWED_DOMAIN):
            raise ConfigurationError(
                f"sources.yaml corpus[{idx}]: URL '{url}' is not on the allowed "
                f"domain '{ALLOWED_DOMAIN}'. Only Groww scheme pages are permitted."
            )

        # EC-P0-002: No duplicate URLs
        if url in seen_urls:
            raise ConfigurationError(
                f"sources.yaml: Duplicate URL detected: '{url}'. "
                "Each scheme must have a unique URL."
            )
        seen_urls.add(url)

        # Duplicate ID check
        if scheme_id in seen_ids:
            raise ConfigurationError(
                f"sources.yaml: Duplicate id detected: '{scheme_id}'."
            )
        seen_ids.add(scheme_id)

        schemes.append(
            SchemeConfig(
                id=scheme_id,
                name=entry["name"],
                category=entry["category"],
                url=url,
                sections_required=entry.get("sections_required", []),
                sections_optional=entry.get("sections_optional", []),
            )
        )

    logger.info(
        "sources.yaml validated: %d schemes loaded from AMC '%s'.",
        len(schemes),
        data["amc"],
    )
    return SourcesConfig(
        version=data["version"],
        updated=data["updated"],
        amc=data["amc"],
        allowed_domain=data["allowed_domain"],
        corpus=schemes,
    )


def _validate_refusal(data: dict, path: Path) -> RefusalConfig:
    """Validate refusal_intents.yaml against all Phase 0 rules."""

    # EC-P0-003: Required top-level keys
    required_keys = (
        "advisory_patterns",
        "advisory_semantic_examples",
        "canned_refusal",
        "pii_block",
        "dont_know_without_link",
        "empty_query",
    )
    for key in required_keys:
        if key not in data:
            raise ConfigurationError(
                f"refusal_intents.yaml missing required key: '{key}'"
            )

    patterns: List[str] = data["advisory_patterns"]
    if not isinstance(patterns, list) or len(patterns) < MIN_REFUSAL_PATTERNS:
        raise ConfigurationError(
            f"refusal_intents.yaml: 'advisory_patterns' must be a list with at least "
            f"{MIN_REFUSAL_PATTERNS} entries; found {len(patterns) if isinstance(patterns, list) else 0}."
        )

    examples: List[str] = data["advisory_semantic_examples"]
    if not isinstance(examples, list) or len(examples) < MIN_ADVISORY_EXAMPLES:
        raise ConfigurationError(
            f"refusal_intents.yaml: 'advisory_semantic_examples' must be a list with "
            f"at least {MIN_ADVISORY_EXAMPLES} entries."
        )

    # EC-P0-006: canned_refusal must contain {scheme_url} placeholder
    canned: str = data["canned_refusal"]
    if REQUIRED_PLACEHOLDER not in canned:
        raise ConfigurationError(
            f"refusal_intents.yaml: 'canned_refusal' must contain the placeholder "
            f"'{REQUIRED_PLACEHOLDER}' but it was not found."
        )

    # pii_block and dont_know_without_link must NOT contain {scheme_url} (zero-URL routes)
    for field_name in ("pii_block", "dont_know_without_link"):
        if REQUIRED_PLACEHOLDER in data[field_name]:
            raise ConfigurationError(
                f"refusal_intents.yaml: '{field_name}' must NOT contain "
                f"'{REQUIRED_PLACEHOLDER}' — this route returns zero URLs."
            )

    logger.info(
        "refusal_intents.yaml validated: %d advisory patterns, %d semantic examples.",
        len(patterns),
        len(examples),
    )
    return RefusalConfig(
        version=data.get("version", "1.0.0"),
        updated=data.get("updated", ""),
        advisory_patterns=patterns,
        advisory_semantic_examples=examples,
        canned_refusal=canned,
        pii_block=data["pii_block"],
        dont_know_without_link=data["dont_know_without_link"],
        empty_query=data["empty_query"],
    )


def _validate_thresholds(data: dict, path: Path) -> ThresholdsConfig:
    """Validate thresholds.yaml; raise on missing or nonsensical values."""

    def _get(section: str, key: str, expected_type: type):
        if section not in data:
            raise ConfigurationError(f"thresholds.yaml missing section: '{section}'")
        if key not in data[section]:
            raise ConfigurationError(
                f"thresholds.yaml missing key: '{section}.{key}'"
            )
        val = data[section][key]
        if not isinstance(val, expected_type):
            raise ConfigurationError(
                f"thresholds.yaml '{section}.{key}' must be {expected_type.__name__}, "
                f"got {type(val).__name__}."
            )
        return val

    r = data.get("retrieval", {})
    c = data.get("confidence", {})
    ch = data.get("chunking", {})
    f = data.get("fetching", {})
    d = data.get("drift", {})
    l = data.get("llm", {})
    a = data.get("api", {})

    cfg = ThresholdsConfig(
        dense_top_k=_get("retrieval", "dense_top_k", int),
        sparse_top_k=_get("retrieval", "sparse_top_k", int),
        rrf_k=_get("retrieval", "rrf_k", int),
        rrf_merged_n=_get("retrieval", "rrf_merged_n", int),
        section_boost_factor=float(_get("retrieval", "section_boost_factor", (int, float))),
        reranker_input_n=_get("retrieval", "reranker_input_n", int),
        reranker_output_n=_get("retrieval", "reranker_output_n", int),
        factual_threshold=float(_get("confidence", "factual_threshold", (int, float))),
        ambiguous_threshold=float(_get("confidence", "ambiguous_threshold", (int, float))),
        token_soft_cap=_get("chunking", "token_soft_cap", int),
        token_overlap=_get("chunking", "token_overlap", int),
        min_expected_chunks=_get("chunking", "min_expected_chunks", int),
        min_chunk_text_length=_get("chunking", "min_chunk_text_length", int),
        request_timeout_seconds=_get("fetching", "request_timeout_seconds", int),
        max_retries=_get("fetching", "max_retries", int),
        retry_base_delay_seconds=_get("fetching", "retry_base_delay_seconds", int),
        min_content_bytes=_get("fetching", "min_content_bytes", int),
        freeze_threshold=float(_get("drift", "freeze_threshold", (int, float))),
        raw_snapshots_keep_last=_get("drift", "raw_snapshots_keep_last", int),
        max_tokens=_get("llm", "max_tokens", int),
        temperature=float(_get("llm", "temperature", (int, float))),
        max_soft_retries=_get("llm", "max_soft_retries", int),
        max_question_length=_get("api", "max_question_length", int),
        max_concurrent_requests=_get("api", "max_concurrent_requests", int),
        ask_timeout_seconds=_get("api", "ask_timeout_seconds", int),
    )

    # Sanity checks
    if not (0.0 <= cfg.factual_threshold <= 1.0):
        raise ConfigurationError(
            "thresholds.yaml: 'confidence.factual_threshold' must be between 0.0 and 1.0."
        )
    if not (0.0 < cfg.freeze_threshold <= 1.0):
        raise ConfigurationError(
            "thresholds.yaml: 'drift.freeze_threshold' must be between 0.0 and 1.0."
        )
    if cfg.token_overlap >= cfg.token_soft_cap:
        raise ConfigurationError(
            "thresholds.yaml: 'chunking.token_overlap' must be less than 'chunking.token_soft_cap'."
        )

    logger.info("thresholds.yaml validated.")
    return cfg


def _validate_disclaimer(text: str) -> str:
    """EC-P0-004: Disclaimer must be non-empty."""
    if len(text.strip()) < 20:
        raise ConfigurationError(
            "disclaimer.txt is too short or empty. "
            "The disclaimer must be at least 20 characters."
        )
    logger.info("disclaimer.txt validated (%d characters).", len(text))
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(config_dir: Optional[Path] = None) -> AppConfig:
    """
    Load and validate all Phase 0 configuration files.

    Args:
        config_dir: Override the config directory path. Defaults to
                    <project_root>/config/. Useful for testing.

    Returns:
        AppConfig: Fully validated, typed configuration object.

    Raises:
        ConfigurationError: If any config file is missing, malformed,
                            or violates a governance rule.
    """
    base = Path(config_dir) if config_dir else CONFIG_DIR

    # ---- Load raw files ------------------------------------------------
    sources_path = base / "sources.yaml"
    refusal_path = base / "refusal_intents.yaml"
    disclaimer_path = base / "disclaimer.txt"
    thresholds_path = base / "thresholds.yaml"

    sources_raw = _load_yaml(sources_path)
    refusal_raw = _load_yaml(refusal_path)
    thresholds_raw = _load_yaml(thresholds_path)
    disclaimer_text = _load_text(disclaimer_path)

    # ---- Validate ------------------------------------------------------
    sources_cfg = _validate_sources(sources_raw, sources_path)
    refusal_cfg = _validate_refusal(refusal_raw, refusal_path)
    thresholds_cfg = _validate_thresholds(thresholds_raw, thresholds_path)
    disclaimer_validated = _validate_disclaimer(disclaimer_text)

    # ---- Compute config hash for cache busting -------------------------
    raw_bytes = (
        sources_path.read_bytes()
        + refusal_path.read_bytes()
        + thresholds_path.read_bytes()
        + disclaimer_path.read_bytes()
    )
    config_hash = hashlib.sha256(raw_bytes).hexdigest()

    logger.info("All Phase 0 config files loaded and validated. Hash: %s", config_hash[:12])

    return AppConfig(
        sources=sources_cfg,
        refusal=refusal_cfg,
        thresholds=thresholds_cfg,
        disclaimer=disclaimer_validated,
        config_hash=config_hash,
    )


# ---------------------------------------------------------------------------
# CLI helper — validate configs from the command line
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        cfg = load_config()
        print("\n✅ All configuration files are valid.\n")
        print(f"  AMC          : {cfg.sources.amc}")
        print(f"  Corpus URLs  : {len(cfg.sources.corpus)}")
        for s in cfg.sources.corpus:
            print(f"    [{s.id}] {s.url}")
        print(f"  Refusal patterns : {len(cfg.refusal.advisory_patterns)}")
        print(f"  Config hash      : {cfg.config_hash[:16]}...")
        sys.exit(0)
    except ConfigurationError as exc:
        print(f"\n❌ Configuration error: {exc}\n", file=sys.stderr)
        sys.exit(1)
