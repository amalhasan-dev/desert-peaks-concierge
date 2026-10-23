"""PII redaction used by guardrails, logging and memory (rubric 4.4).

Scrubs data BEFORE it is stored anywhere (session history, logs, memory).
Production upgrade: replace the regexes with Google Cloud Sensitive Data
Protection (Cloud DLP) `deidentify_content`, which detects 150+ info types.
"""

import re
from typing import Any

PATTERNS = {
    # 13-16 digits, optionally separated by spaces or dashes.
    "CARD_NUMBER": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    # Phone-like runs; only counted as PHONE if they contain 10-15 digits
    # (so dates like 2026-10-25, which have 8 digits, are NOT redacted).
    "PHONE": re.compile(r"(?<!\d)\+?\d[\d\s().-]{8,}\d(?!\d)"),
}


def _is_phone(match: "re.Match[str]") -> bool:
    return 10 <= sum(c.isdigit() for c in match.group()) <= 15


def find_pii(text: str) -> list[str]:
    """Returns the PII types found in text, e.g. ["CARD_NUMBER"]."""
    found = []
    for name, rx in PATTERNS.items():
        matches = list(rx.finditer(text or ""))
        if name == "PHONE":
            matches = [m for m in matches if _is_phone(m)]
        if matches:
            found.append(name)
    return found


def redact_text(text: str) -> str:
    """Replaces every PII match with a [REDACTED_<TYPE>] placeholder."""
    for name, rx in PATTERNS.items():
        if name == "PHONE":
            text = rx.sub(lambda m: "[REDACTED_PHONE]" if _is_phone(m) else m.group(), text)
        else:
            text = rx.sub(f"[REDACTED_{name}]", text)
    return text


def redact(value: Any) -> Any:
    """Recursively redacts strings inside dicts/lists (for log payloads)."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value
