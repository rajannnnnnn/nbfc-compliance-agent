"""Cross-instrument reference edge extraction. LLD §6.5.

The edge that matters most in v1 is DL2025/p8/i --incorporates--> KFS2024: without it the
system can establish that a Key Facts Statement was issued but not whether it was complete,
because the digital lending instrument does not restate the field list.
"""

import re

from pydantic import BaseModel

from app.corpus.parsers.base import ClauseNode

CIRCULAR_RE = re.compile(
    r"(?:circular\s+no\.?\s*)?([A-Z]{2,4}(?:\.[A-Z]{2,4})*\.REC\.\d+/[\d.]+/\d{4}-\d{2})",
    re.IGNORECASE,
)

_INCORPORATES_PHRASES = ("as per instructions contained in", "in terms of", "shall comply with")
_REPEAL_SECTION_MARKERS = ("repeal", "repealed", "supersede", "superseded")
_AMENDMENT_INSTRUMENT_MARKER = "amendment"


class ReferenceEdge(BaseModel):
    from_clause_path: str
    to_instrument_code: str
    to_clause_path: str | None
    reference_text: str
    reference_kind: str


def extract_references(
    nodes: list[ClauseNode],
    known_instruments: dict[str, list[str]],
    *,
    instrument_is_amendment: bool = False,
) -> list[ReferenceEdge]:
    """`known_instruments` maps instrument_code -> title-match patterns (regex strings) used
    to recognise a reference to that instrument by its official title when no circular number
    is quoted inline."""
    edges: list[ReferenceEdge] = []

    for node in nodes:
        text_lower = node.text.lower()
        for code, title_patterns in known_instruments.items():
            matched_title = any(re.search(p, node.text, re.IGNORECASE) for p in title_patterns)
            circular_match = CIRCULAR_RE.search(node.text)
            if not matched_title and not circular_match:
                continue

            if any(p in text_lower for p in _REPEAL_SECTION_MARKERS):
                kind = "repeals"
            elif instrument_is_amendment:
                kind = "amends"
            elif any(p in text_lower for p in _INCORPORATES_PHRASES):
                kind = "incorporates"
            else:
                kind = "see_also"

            edges.append(
                ReferenceEdge(
                    from_clause_path=node.clause_path,
                    to_instrument_code=code,
                    to_clause_path=None,
                    reference_text=node.text[:300],
                    reference_kind=kind,
                )
            )

    return edges
