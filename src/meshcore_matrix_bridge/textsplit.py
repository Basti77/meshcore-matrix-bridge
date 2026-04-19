"""Utilities for splitting text messages for the MeshCore radio link.

The Companion firmware has a limited MTU for channel/DM payloads. A safe
conservative cap is ~140 chars per outgoing message. We split on word
boundaries when possible and prefix every part with ``(i/n)`` so a reader
can reassemble.
"""
from __future__ import annotations


MAX_CHARS_DEFAULT = 140


def split_for_radio(text: str, max_chars: int = MAX_CHARS_DEFAULT) -> list[str]:
    text = text.replace("\r\n", "\n").rstrip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # word-boundary split
    words = text.split(" ")
    parts: list[str] = []
    cur = ""
    for w in words:
        # reserve "(i/n) " prefix → 6–8 chars; use max_chars - 8 as budget
        budget = max_chars - 8
        if not cur:
            candidate = w
        else:
            candidate = cur + " " + w
        if len(candidate) <= budget:
            cur = candidate
        else:
            if cur:
                parts.append(cur)
            # if single word still too long, hard-split it
            while len(w) > budget:
                parts.append(w[:budget])
                w = w[budget:]
            cur = w
    if cur:
        parts.append(cur)

    n = len(parts)
    if n == 1:
        return parts
    return [f"({i+1}/{n}) {p}" for i, p in enumerate(parts)]
