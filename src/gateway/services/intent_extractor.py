"""Rule-based intent extractor — implements :class:`IntentExtractor`.

Strips parameters (order IDs, numbers, emails, dates, URLs) from a prompt and returns the
canonical (parameter-free) form plus the bare values. The canonical form is the intent-match
key; the values are persisted in ``intent_entries`` for the gate's binding check (D25).

This is a real-enough extractor to exercise the seam and produce meaningful eval results.
A model-backed or NER-based extractor can replace it behind the same port without touching
the gate or the pipeline.
"""

from __future__ import annotations

import re

from gateway.domain.models import ExtractedIntent

# Patterns ordered from most-specific to least-specific to avoid double-extraction.
# Each tuple: (compiled regex, placeholder string)
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # ISO-8601 dates and common variants (2024-01-15, 01/15/2024, Jan 15 2024)
    (
        re.compile(
            r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,?\s+\d{4})?)\b",
            re.IGNORECASE,
        ),
        "{DATE}",
    ),
    # Email addresses
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "{EMAIL}"),
    # URLs (http/https)
    (re.compile(r"https?://\S+"), "{URL}"),
    # Quoted literals — the operand of a "translate 'X'", "define 'X'" style intent. The inner
    # value is the parameter; an answer that reuses it (e.g. "'Hello' is 'Hola'") is bound to it.
    (re.compile(r"['\"]([^'\"]+)['\"]"), "{STR}"),
    # Order/ticket/ID patterns: alphanumeric codes with optional prefixes (#123, ORD-456, ABC123)
    (re.compile(r"\b(?:#\d+|[A-Z]{2,}-\d+|[A-Z]+\d{3,}|\d{4,})\b"), "{ID}"),
    # Standalone numbers (integers and decimals, not already matched above)
    (re.compile(r"\b\d+(?:\.\d+)?\b"), "{N}"),
]


class RegexIntentExtractor:
    """Strips parameters via ordered regex patterns. Implements ``IntentExtractor``."""

    def extract(self, prompt: str) -> ExtractedIntent:
        canonical = prompt
        parameters: list[str] = []
        for pattern, placeholder in _PATTERNS:
            matches = pattern.findall(canonical)
            if matches:
                parameters.extend(str(m) for m in matches)
                canonical = pattern.sub(placeholder, canonical)
        # Normalize: collapse whitespace, lowercase for a stable intent-match key.
        canonical = " ".join(canonical.split()).lower()
        return ExtractedIntent(canonical=canonical, parameters=parameters)
