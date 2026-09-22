"""ParsedInstrument tree types + Parser protocol. LLD §6.2."""

from typing import Protocol

from pydantic import BaseModel

from app.domain.enums import ChunkKind


class ClauseNode(BaseModel):
    chapter: str | None = None
    chapter_title: str | None = None
    section_letter: str | None = None
    section_title: str | None = None
    para_number: str
    para_sort: int
    level2_label: str | None = None
    level3_label: str | None = None
    heading: str | None = None
    text: str
    order: int
    chunk_kind: ChunkKind = ChunkKind.CLAUSE
    # ADR-005: borrower-class scoping tagged during parsing (e.g. the microfinance conduct
    # block heading), empty means applies to all borrower classes.
    applies_to_borrower_classes: list[str] = []

    @property
    def clause_path(self) -> str:
        """HLD §4.1 canonical format: '{instrument_code}/p{para}[/{level2}][/{level3}]' for a
        numbered paragraph ('DL2025/p9/ii'), or '{instrument_code}/{para}[...]' verbatim for a
        non-numeric para_number like 'annexA' ('KFS2024/annexA/part2/3') — the leading digit
        is what distinguishes the two forms."""
        first_part = f"p{self.para_number}" if self.para_number[:1].isdigit() else self.para_number
        parts = [first_part]
        if self.level2_label:
            parts.append(self.level2_label)
        if self.level3_label:
            parts.append(self.level3_label)
        return "/".join(parts)


class ParsedInstrument(BaseModel):
    code: str
    parser_version: str
    nodes: list[ClauseNode]
    detected_para_range: tuple[str, str]
    warnings: list[str]


class Parser(Protocol):
    version: str

    def parse(self, text: str) -> ParsedInstrument: ...


def para_sort_key(para_number: str) -> int:
    """'100W' -> 100. The sort key is the leading integer; the letter suffix is a secondary
    text sort handled by (para_sort, para_number) tuple ordering wherever clauses are listed."""
    digits = ""
    for ch in para_number:
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits) if digits else 0
