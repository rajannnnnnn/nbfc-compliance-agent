"""The citation validator. LLD §10.2 — the one place CLAUDE.md §2.1's guarantee is enforced
in code, not by prompt instruction. A model response that fails here becomes `no_clause_found`
and is logged; it is never passed through.

Per ADR-025 (SQ-18): the LLD's own literal branch order `continue`s a context_only citation
before the `is_literal_substring` check runs, so a context_only excerpt is never verified —
yet §17.2 computes `hallucinated_citation_rate` over *all* persisted citations, context_only
included. That makes the release-blocking metric non-zero by construction. Fixed here: every
citation, regardless of role, is checked against `by_path(...).text` before being kept.
"""

import re
from datetime import date

from pydantic import BaseModel

from app.domain.clauses import ClauseCandidateSet
from app.domain.enums import CitationRejectReason
from app.domain.verdicts import Citation, VerdictDraft

CONCLUSIVE = {"compliant", "violation", "ambiguous"}

_WS_RE = re.compile(r"\s+")


def _normalise_ws(s: str) -> str:
    return _WS_RE.sub(" ", s).strip()


def is_literal_substring(excerpt: str, clause_text: str) -> bool:
    """Whitespace-normalised, otherwise exact. No fuzzy matching — a model that paraphrases
    a clause while claiming to quote it is producing exactly the defect this system exists
    to prevent."""
    if not excerpt:
        return False
    return _normalise_ws(excerpt) in _normalise_ws(clause_text)


class RejectedCitation(BaseModel):
    citation: Citation
    reason: CitationRejectReason


class ValidationOutcome(BaseModel):
    verdict: str
    citations: list[Citation]
    downgraded: bool
    reason: str | None
    rejected: list[RejectedCitation] = []


def _as_context(citations: list[Citation]) -> list[Citation]:
    return [c.model_copy(update={"role": "context_only"}) for c in citations]


def validate(
    draft: VerdictDraft, candidates: ClauseCandidateSet, *, as_of: date
) -> ValidationOutcome:
    allowed = candidates.paths()
    ctx_ok = {c.clause_path for c in candidates.context_only}

    kept: list[Citation] = []
    rejected: list[RejectedCitation] = []

    for cit in draft.citations:
        if cit.role == "context_only":
            if cit.clause_path not in ctx_ok:
                rejected.append(
                    RejectedCitation(citation=cit, reason=CitationRejectReason.NOT_OFFERED)
                )
                continue
            clause = candidates.by_path(cit.clause_path)
            if clause is None or not is_literal_substring(cit.quoted_clause_excerpt, clause.text):
                rejected.append(
                    RejectedCitation(
                        citation=cit, reason=CitationRejectReason.EXCERPT_NOT_SUBSTRING
                    )
                )
                continue
            kept.append(cit)
            continue

        if cit.clause_path not in allowed:
            rejected.append(RejectedCitation(citation=cit, reason=CitationRejectReason.NOT_OFFERED))
            continue

        clause = candidates.by_path(cit.clause_path)
        if clause is None or not clause.citable:
            rejected.append(RejectedCitation(citation=cit, reason=CitationRejectReason.NOT_CITABLE))
            continue
        if clause.effective_from and clause.effective_from > as_of:
            rejected.append(
                RejectedCitation(citation=cit, reason=CitationRejectReason.NOT_IN_FORCE)
            )
            continue
        if clause.effective_to and clause.effective_to <= as_of:
            rejected.append(
                RejectedCitation(citation=cit, reason=CitationRejectReason.NOT_IN_FORCE)
            )
            continue
        if not is_literal_substring(cit.quoted_clause_excerpt, clause.text):
            rejected.append(
                RejectedCitation(citation=cit, reason=CitationRejectReason.EXCERPT_NOT_SUBSTRING)
            )
            continue
        kept.append(cit)

    decisive = [c for c in kept if c.role == "decisive"]

    if draft.verdict in CONCLUSIVE and not decisive:
        return ValidationOutcome(
            verdict="no_clause_found",
            citations=_as_context(kept),
            downgraded=True,
            reason="no_valid_decisive_citation",
            rejected=rejected,
        )
    if draft.verdict == "ambiguous" and len(decisive) < 2:
        return ValidationOutcome(
            verdict="ambiguous",
            citations=kept,
            downgraded=False,
            reason="single_decisive_citation_recorded",
            rejected=rejected,
        )
    if draft.verdict == "no_clause_found" and decisive:
        # Model contradicted itself — the abstention is trusted; decisive citations demote
        # to context rather than being discarded, so the audit trail keeps what it saw.
        return ValidationOutcome(
            verdict="no_clause_found",
            citations=_as_context(kept),
            downgraded=True,
            reason="abstention_with_citations",
            rejected=rejected,
        )
    return ValidationOutcome(
        verdict=draft.verdict, citations=kept, downgraded=False, reason=None, rejected=rejected
    )
