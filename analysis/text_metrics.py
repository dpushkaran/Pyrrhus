"""Compute text-level quality and verbosity metrics for agent outputs."""

from __future__ import annotations

import gzip
import re
from collections import Counter

from models import TextMetrics

# Phrases that pad output without adding information.
FILLER_PHRASES = [
    "it is important to note",
    "it's important to note",
    "it is worth noting",
    "it's worth noting",
    "as mentioned earlier",
    "as previously mentioned",
    "as noted above",
    "in order to",
    "for the purpose of",
    "at the end of the day",
    "in today's world",
    "it goes without saying",
    "needless to say",
    "essentially",
    "basically",
    "fundamentally",
    "in conclusion",
    "to summarize",
    "in summary",
    "overall",
    "moving forward",
    "going forward",
    "it should be noted that",
    "it can be seen that",
    "the fact that",
]

_SENTENCE_SPLIT = re.compile(r"[.!?]+\s+")
_WORD_SPLIT = re.compile(r"\b[a-zA-Z]+\b")


def _type_token_ratio(words: list[str]) -> float:
    if not words:
        return 0.0
    return len(set(words)) / len(words)


def _compression_ratio(text: str) -> float:
    raw = text.encode("utf-8")
    if len(raw) == 0:
        return 0.0
    compressed = gzip.compress(raw, compresslevel=6)
    return len(compressed) / len(raw)


def _ngram_repetition_rate(words: list[str], n: int = 3) -> float:
    """Fraction of n-grams that appear more than once."""
    if len(words) < n:
        return 0.0
    ngrams = [tuple(words[i : i + n]) for i in range(len(words) - n + 1)]
    counts = Counter(ngrams)
    repeated = sum(1 for c in counts.values() if c > 1)
    return repeated / len(counts) if counts else 0.0


def _avg_sentence_length(text: str) -> float:
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if not sentences:
        return 0.0
    word_counts = [len(_WORD_SPLIT.findall(s)) for s in sentences]
    return sum(word_counts) / len(word_counts)


def _filler_phrase_count(text_lower: str) -> int:
    return sum(text_lower.count(phrase) for phrase in FILLER_PHRASES)


def compute_text_metrics(text: str) -> TextMetrics:
    """Analyse *text* and return a TextMetrics with all computed fields."""
    if not text or not text.strip():
        return TextMetrics()

    text_lower = text.lower()
    words = _WORD_SPLIT.findall(text_lower)

    return TextMetrics(
        word_count=len(words),
        type_token_ratio=round(_type_token_ratio(words), 4),
        compression_ratio=round(_compression_ratio(text), 4),
        ngram_repetition_rate=round(_ngram_repetition_rate(words), 4),
        avg_sentence_length=round(_avg_sentence_length(text), 2),
        filler_phrase_count=_filler_phrase_count(text_lower),
    )
