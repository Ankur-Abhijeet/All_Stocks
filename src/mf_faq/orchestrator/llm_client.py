"""
src/mf_faq/orchestrator/llm_client.py
======================================
Interfaces with the Groq API to generate answers.
"""

import os
import logging
from typing import List, Optional
from datetime import date

from mf_faq.retrieval.hybrid_retriever import RetrievedChunk

logger = logging.getLogger(__name__)


class LLMClient:
    SYSTEM_PROMPT = """You are a facts-only assistant for HDFC Mutual Fund schemes.

Rules (STRICT):
1. You MUST answer the question using the context. ADDITIONALLY, you MUST provide a detailed explanation of the financial concepts mentioned (such as what an 'exit load', 'expense ratio', or 'AUM' is) to ensure the user fully understands the context. Your explanation must be educational and thorough.
2. Maximum 10 sentences. Please provide a detailed and comprehensive answer within this limit.
3. You MUST explicitly append 'Source URL: <the_url_from_context>' on a new line ONLY IF you can answer the question based on the context.
4. End with: "Last updated from sources: {date}"
5. NEVER say: recommend, should invest, better than, will outperform, returns will be.
6. If the answer is not in the context, say: "I couldn't find a verified factual answer for that in the official Groww documents." Do NOT attach any URLs in this case.
7. If the user includes any personal information (PII), immediately refuse to answer and do NOT attach any URLs.
"""

    def __init__(self):
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
            
        self.api_key = os.getenv("GROQ_API_KEY")
        if self.api_key:
            try:
                from groq import Groq
                self.client = Groq(api_key=self.api_key)
                self.model = "llama-3.1-8b-instant"
                logger.info(f"Initialized Groq LLM Client with model {self.model}.")
            except ImportError:
                logger.warning("groq library not installed. Falling back to extractive mode.")
                self.client = None
        else:
            logger.warning("GROQ_API_KEY not found. Falling back to extractive mode.")
            self.client = None

    def generate(self, query: str, chunks: List[RetrievedChunk], repair_instruction: str = "", history: Optional[List[dict]] = None) -> str:
        """
        Generate a factual answer using the retrieved chunks.
        """
        today = str(date.today())
        
        # Build context
        context_str = "\n\n".join(
            f"--- Chunk {i+1} ---\n{c.chunk.text}\nSource URL: {c.chunk.source_url}"
            for i, c in enumerate(chunks)
        )
        
        prompt = f"Context:\n{context_str}\n\nUser Question: {query}"
        if repair_instruction:
            prompt += f"\n\nIMPORTANT CORRECTION: {repair_instruction}"

        if self.client:
            # Call Groq
            messages = [{"role": "system", "content": self.SYSTEM_PROMPT.format(date=today)}]
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": prompt})
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
                max_tokens=1024,
                top_p=1.0,
            )
            return response.choices[0].message.content.strip()
        else:
            # Extractive fallback: just return the first sentence of the top chunk + footer + url
            if chunks:
                top_chunk = chunks[0].chunk
                first_sentence = top_chunk.text.split(". ")[0] + "."
                return f"{first_sentence}\n\nSource URL: {top_chunk.source_url}\nLast updated from sources: {today}"
            else:
                return f"I don't have a verified answer for that.\nLast updated from sources: {today}"
