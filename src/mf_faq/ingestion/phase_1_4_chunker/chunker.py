"""
src/mf_faq/ingestion/phase_1_4_chunker/chunker.py
===================================================
Phase 1.4 — Chunker

Responsibility: Convert cleaned text sections into retrieval-optimized chunks 
with full provenance metadata. Given the realities of the extracted mutual fund 
data (extremely short factual fields like `0.8%` or `INR 500`), token-window 
splitting is unnecessary and detrimental.

Input:  CleanedScheme  (from Phase 1.3 Cleaner)
Output: List[Chunk]  (~7 chunks per scheme → ~35 total across 5 schemes)

Chunking strategy:
    1. Context-Enriched Section Mapping: 1 chunk per section.
    2. Contextualization: Prepend `Scheme: {name}\\nSection: {key}\\nContent: ` to tiny texts.
    3. Split/Overlap: None. Sections are factual and short; splitting breaks context.

Chunk metadata fields:
    chunk_id      : "{scheme_id}_{section_key}"  (unique across all schemes)
    scheme_id     : e.g. 'hdfc_mid_cap'
    scheme_name   : Human-readable scheme name
    section_key   : e.g. 'expense_ratio'
    source_url    : Whitelisted Groww URL (used as citation in answers)
    text          : Context-enriched chunk text content
    token_count   : Approximate whitespace-split token count
    content_hash  : SHA-256 of text (used by Phase 1.7 drift detection)

Edge cases:
    P1CH-EC-003: Chunk ID collision → ChunkIDCollisionError
    P1CH-EC-004: Chunk is whitespace/punctuation only → drop
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import List

from mf_faq.ingestion.phase_1_3_cleaner.cleaner import CleanedScheme


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ChunkIDCollisionError(Exception):
    """Raised if two chunks in the same run produce the same chunk_id."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Chunk:
    """
    A single retrieval-optimised text chunk with full provenance metadata.

    content_hash is SHA-256 of text.encode('utf-8') — used for drift detection.
    """

    chunk_id: str        # "{scheme_id}_{section_key}"
    scheme_id: str
    scheme_name: str
    section_key: str
    source_url: str      # Whitelisted Groww URL
    text: str
    token_count: int
    content_hash: str    # SHA-256 hex digest

    @classmethod
    def build(cls, scheme_id: str, scheme_name: str, section_key: str,
              source_url: str, text: str) -> "Chunk":
        """Factory method that computes token_count and content_hash automatically."""
        # Enriched context
        enriched_text = f"Scheme: {scheme_name}\nSection: {section_key}\nContent: {text}"
        token_count = len(enriched_text.split())
        content_hash = hashlib.sha256(enriched_text.encode("utf-8")).hexdigest()
        chunk_id = f"{scheme_id}_{section_key}"
        return cls(
            chunk_id=chunk_id,
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            section_key=section_key,
            source_url=source_url,
            text=enriched_text,
            token_count=token_count,
            content_hash=content_hash,
        )


# ---------------------------------------------------------------------------
# Chunker class
# ---------------------------------------------------------------------------


class Chunker:
    """
    Phase 1.4 — CleanedScheme → List[Chunk] section-aware mapping.
    """

    def chunk(self, cleaned: CleanedScheme) -> List[Chunk]:
        """
        Map a CleanedScheme into retrieval-optimised Chunk objects.
        1 chunk per section, no splitting.

        Args:
            cleaned: CleanedScheme from Phase 1.3

        Returns:
            List[Chunk] with guaranteed unique chunk_ids across all schemes.

        Raises:
            ChunkIDCollisionError: If duplicate chunk_ids are detected.
        """
        chunks = []
        seen_chunk_ids = set()

        for section_key, text in cleaned.sections.items():
            if not text.strip():
                # P1CH-EC-004: Post-split (or map) chunk is whitespace only
                continue

            chunk = Chunk.build(
                scheme_id=cleaned.scheme_id,
                scheme_name=cleaned.scheme_name,
                section_key=section_key,
                source_url=cleaned.source_url,
                text=text
            )

            if chunk.chunk_id in seen_chunk_ids:
                raise ChunkIDCollisionError(f"Duplicate chunk_id detected: {chunk.chunk_id}")
            seen_chunk_ids.add(chunk.chunk_id)
            chunks.append(chunk)

        return chunks
