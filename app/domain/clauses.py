from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import ExclusionReason


class ClauseRef(BaseModel):
    clause_id: UUID
    clause_path: str
    instrument_code: str
    effective_from: date | None
    effective_to: date | None
    citable: bool


class ClauseCandidate(ClauseRef):
    heading: str | None
    text: str
    source: Literal["pinned", "vector", "lexical", "reference_hop"]
    rank: int
    score: float
    exclusion_reason: ExclusionReason | None = None
    context_note: str | None = None


class ClauseCandidateSet(BaseModel):
    as_of: date
    entity_type: str
    borrower_class: str
    candidates: list[ClauseCandidate]
    context_only: list[ClauseCandidate] = []
    snapshot_id: UUID

    def paths(self) -> set[str]:
        return {c.clause_path for c in self.candidates}

    def by_path(self, path: str) -> ClauseCandidate | None:
        """Resolves a path across both candidates and context_only. Called by the citation
        validator (LLD §10.2), which never defines it — added here. See ADR-011."""
        for c in self.candidates:
            if c.clause_path == path:
                return c
        for c in self.context_only:
            if c.clause_path == path:
                return c
        return None
