"""Redaction profile 'v1'. LLD §13.

Ordering matters. The LLD's own prose says "ACCOUNT before PHONE would swallow ten-digit
phone numbers" but its literal list put ACCOUNT (a 9-18 digit pattern) ahead of PHONE anyway —
an internal inconsistency caught only by actually running the ordering test below: a bare
10-digit mobile number matched ACCOUNT first and was gone by the time the PHONE pattern ran.
PHONE is placed before ACCOUNT here so a phone-shaped number is tagged PHONE; ACCOUNT still
catches everything else in its 9-18 digit range, including a 10-digit account number that
happens not to start with a mobile prefix (6-9).

Names are handled separately (not by a general name matcher — a general matcher redacts the
word "Gold" in "Gold Loan Agreement") and are out of scope here; the borrower's own name is
redacted by the caller from a field it already knows is a name.
"""

import re

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AADHAAR", re.compile(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("PHONE", re.compile(r"(?:\+91[\s-]?)?\b[6-9]\d{9}\b")),
    ("ACCOUNT", re.compile(r"\b\d{9,18}\b")),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("GST", re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d]{2}\b")),
]


def redact(text: str, *, exempt: bool = False) -> tuple[str, list[str]]:
    """Returns (redacted_text, tags_applied). Each match is replaced with
    '[REDACTED:<TAG>]'. When exempt is True (field.redaction_exempt), returns the text
    unchanged — used for the lender's own published contact details, which are not borrower
    PII and which rules must be able to compare."""
    if exempt:
        return text, []

    tags_applied: list[str] = []
    result = text
    for tag, pattern in PATTERNS:
        if pattern.search(result):
            tags_applied.append(tag)
            result = pattern.sub(f"[REDACTED:{tag}]", result)
    return result, tags_applied
