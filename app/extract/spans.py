"""Span capture and span-grounding verification. LLD §13.1 / HLD §3.

The span-grounding check is the cheapest available hallucination detector: a fact whose
quoted evidence does not appear verbatim in the source is dropped and counted, never trusted.
Budget enforcement runs inside the same transaction as the fact insert, under a row lock on
`document`, so two concurrent writers cannot together exceed the 15% cap.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.facts import Span


def verify_span(quoted: str, source_text: str) -> bool:
    """A span is grounded only if it is a literal (not fuzzy) substring of the source."""
    return quoted in source_text


def build_span(start: int, end: int, quoted: str, source_text: str) -> Span:
    verified = verify_span(quoted, source_text)
    return Span(start=start, end=end, quoted=quoted, verified=verified)


async def admit_span(
    session: AsyncSession, *, document_id: str, span_len: int, settings: Settings
) -> tuple[bool, bool]:
    """Locks the document row, checks the budget, and atomically increments span_used_chars
    if admitted. Returns (admitted, truncated) — `truncated` is set when the span had to be
    shortened to fit rather than dropped outright; a fact whose evidence does not fit at all
    is still stored, only its evidence is shortened (LLD §13.1: "The fact itself is still
    stored — only its evidence is shortened")."""
    row = await session.execute(
        text(
            "SELECT char_count, span_budget_chars, span_used_chars FROM document "
            "WHERE id = :id FOR UPDATE"
        ),
        {"id": document_id},
    )
    char_count, budget_chars, used_chars = row.one()
    remaining = budget_chars - used_chars

    if remaining <= 0:
        return False, True

    admitted_len = min(span_len, remaining)
    truncated = admitted_len < span_len

    await session.execute(
        text("UPDATE document SET span_used_chars = span_used_chars + :inc WHERE id = :id"),
        {"inc": admitted_len, "id": document_id},
    )
    return True, truncated


def truncate_longest_first(spans: list[tuple[str, int]], budget_remaining: int) -> list[str]:
    """Given [(fact_id, span_len), ...] sorted by nothing in particular, truncates the
    longest spans first until the total fits the remaining budget. Returns the fact_ids to
    truncate, longest first."""
    sorted_spans = sorted(spans, key=lambda x: x[1], reverse=True)
    total = sum(length for _, length in spans)
    to_truncate: list[str] = []
    for fact_id, length in sorted_spans:
        if total <= budget_remaining:
            break
        to_truncate.append(fact_id)
        total -= length
    return to_truncate
