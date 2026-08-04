"""PII masking for text that leaves this machine.

Why this exists: prompts are sent to third-party LLM APIs (Gemini, Groq, …).
Anything a user types into a research question travels to those providers, so
identifiers in user input are masked before they go out and before they land
in logs/traces.

SCOPE — deliberately narrow, and the reason matters:

  masked      user-supplied text (questions, notes) and telemetry payloads
  NOT masked  retrieved SOURCE document text

Masking source text would be actively harmful: the verification gate requires
the model's quote to match the original chunk byte-for-byte. Rewriting an
author's email inside a paper would make every quote from that passage fail,
turning a privacy nicety into a correctness bug. Source documents are public
scholarly material we deliberately ingested — user input is not.

Deterministic regex; no model, no network.
"""

import re

# Ordered: more specific patterns first so they win.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")),
    # Common provider key shapes — never want these in a prompt or a log.
    ("API_KEY", re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|gsk_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{20,}"
        r"|hf_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|tvly-[A-Za-z0-9-]{10,})\b")),
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("IPV4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("PHONE", re.compile(
        r"(?<!\w)(?:\+\d{1,3}[ -]?)?(?:\(\d{3}\)|\d{3})[ -]\d{3}[ -]\d{4}(?!\w)")),
]


def mask_pii(text: str) -> str:
    """Replace detected identifiers with [REDACTED:<KIND>]. Idempotent."""
    if not text:
        return text
    out = text
    for kind, pattern in _PATTERNS:
        out = pattern.sub(f"[REDACTED:{kind}]", out)
    return out


def find_pii(text: str) -> list[str]:
    """Kinds detected in `text` — for logging/metrics without leaking values."""
    if not text:
        return []
    return [kind for kind, pattern in _PATTERNS if pattern.search(text)]
