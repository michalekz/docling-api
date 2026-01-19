"""
LLM Postprocessing module for document analysis.

Uses Claude Haiku to analyze converted markdown and extract:
- summary: Brief description of the document (max 200 chars)
- category: Document type/category
- tags: Keywords for search (3-5 items)
- language: Detected language code (cs, en, de, etc.)
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import List, Optional

import litellm

# Disable LiteLLM verbose logging
litellm.suppress_debug_info = True

logger = logging.getLogger(__name__)

# Model configuration from environment
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
LLM_MODEL = os.getenv("MDCONVERT_LLM_MODEL", DEFAULT_MODEL)

# Maximum characters to send to LLM (to control costs)
MAX_CONTENT_LENGTH = 10000


@dataclass
class AnalysisResult:
    """Result of LLM document analysis."""
    summary: str
    category: str
    tags: List[str]
    language: str


ANALYSIS_PROMPT = """Analyzuj následující dokument a vrať JSON s těmito poli:

1. "summary": Stručný popis dokumentu v 1-2 větách (max 200 znaků). Použij jazyk dokumentu.
2. "category": Kategorie dokumentu. Vyber jednu z:
   - "report" (zpráva, analýza)
   - "contract" (smlouva, právní dokument)
   - "invoice" (faktura, účetní doklad)
   - "presentation" (prezentace)
   - "manual" (návod, dokumentace)
   - "correspondence" (dopis, email)
   - "form" (formulář)
   - "other" (jiné)
3. "tags": Pole 3-5 klíčových slov pro vyhledávání (v jazyce dokumentu)
4. "language": Kód jazyka dokumentu (cs, en, de, sk, pl, ...)

Odpověz POUZE validním JSON objektem, bez dalšího textu.

Dokument:
"""


def analyze_document(markdown_content: str) -> Optional[AnalysisResult]:
    """
    Analyze document content using LLM.

    Args:
        markdown_content: Converted markdown text

    Returns:
        AnalysisResult with summary, category, tags, language
        or None if analysis fails
    """
    if not markdown_content or not markdown_content.strip():
        logger.warning("Empty content, skipping LLM analysis")
        return None

    # Truncate content to control costs
    content = markdown_content[:MAX_CONTENT_LENGTH]
    if len(markdown_content) > MAX_CONTENT_LENGTH:
        content += "\n\n[... obsah zkrácen ...]"

    try:
        logger.info(f"Running LLM postprocessing with model: {LLM_MODEL}")

        response = litellm.completion(
            model=LLM_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": ANALYSIS_PROMPT + content
                }
            ],
            max_tokens=500,
            temperature=0.3,  # Lower temperature for consistent output
        )

        # Extract response text
        response_text = response.choices[0].message.content.strip()

        # Parse JSON response
        try:
            # Handle potential markdown code blocks
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            data = json.loads(response_text)

            result = AnalysisResult(
                summary=data.get("summary", "")[:200],  # Ensure max length
                category=data.get("category", "other"),
                tags=data.get("tags", [])[:5],  # Ensure max 5 tags
                language=data.get("language", "cs"),
            )

            logger.info(f"LLM analysis complete: category={result.category}, language={result.language}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Response was: {response_text[:500]}")
            return None

    except Exception as e:
        logger.error(f"LLM postprocessing failed: {e}")
        return None


def analyze_document_sync(markdown_content: str) -> Optional[AnalysisResult]:
    """
    Synchronous wrapper for analyze_document.

    For use in Celery workers which may not support async.
    """
    return analyze_document(markdown_content)
