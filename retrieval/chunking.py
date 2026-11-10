"""Structure-aware chunking.

Documents arrive as ordered ``(field, text)`` sections rendered by
retrieval.documents. Chunking never crosses a section boundary, so every
chunk keeps exactly one field provenance (a fee chunk never absorbs half
a rewards paragraph). Within a section, sentences are accumulated to a
target token window (400-600 by default) with a fixed token overlap
between consecutive chunks.

Token counts are estimates: one whitespace-separated word counts as one
"token". That is deliberately simple and stable; it slightly undercounts
true BPE tokens for English text, which is acceptable for window sizing.
"""

import re

_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+|\S[^.!?]*$")


def estimate_tokens(text):
    """Approximate token count: whitespace-separated words."""
    if not text:
        return 0
    return len(text.split())


def split_sentences(text):
    return [s.strip() for s in _SENTENCE_RE.findall(text or "") if s.strip()]


def _windows(sentences, target_tokens, max_tokens, overlap_tokens):
    """Yield (text, token_count) windows over a section's sentences."""
    windows = []
    current = []
    current_tokens = 0
    for sentence in sentences:
        stoks = estimate_tokens(sentence)
        if current and current_tokens + stoks > max_tokens:
            windows.append(current)
            # Carry the tail sentences worth roughly overlap_tokens.
            carry = []
            carry_tokens = 0
            for prev in reversed(current):
                ptoks = estimate_tokens(prev)
                if carry and carry_tokens + ptoks > overlap_tokens:
                    break
                carry.insert(0, prev)
                carry_tokens += ptoks
                if carry_tokens >= overlap_tokens:
                    break
            current = carry
            current_tokens = carry_tokens
        current.append(sentence)
        current_tokens += stoks
        if current_tokens >= target_tokens and current_tokens >= max_tokens:
            windows.append(current)
            current, current_tokens = [], 0
    if current:
        windows.append(current)
    return [(" ".join(w), estimate_tokens(" ".join(w))) for w in windows]


def chunk_sections(sections, target_tokens=500, max_tokens=600, overlap_tokens=60):
    """Chunk ordered ``(field, text)`` sections.

    Returns a list of dicts: {field, ordinal, text, token_count}.
    ``target_tokens`` is clamped into [1, max_tokens]; sections shorter
    than the target become a single chunk.
    """
    if max_tokens < 1:
        raise ValueError("max_tokens must be >= 1")
    target_tokens = max(1, min(target_tokens, max_tokens))
    overlap_tokens = max(0, min(overlap_tokens, max_tokens - 1))
    chunks = []
    ordinal = 0
    for field, text in sections:
        text = (text or "").strip()
        if not text:
            continue
        sentences = split_sentences(text)
        for window_text, token_count in _windows(
            sentences, target_tokens, max_tokens, overlap_tokens
        ):
            chunks.append(
                {
                    "field": field,
                    "ordinal": ordinal,
                    "text": window_text,
                    "token_count": token_count,
                }
            )
            ordinal += 1
    return chunks
