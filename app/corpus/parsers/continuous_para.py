"""Parser for the continuous-paragraph-numbering convention shared by DL2025 and RBC2025
(and its amendment). LLD §6.2, algorithm reproduced in the module docstring of each method.

Ambiguity handled explicitly, by stack context rather than marker shape alone (LLD §6.2):
a lower-roman level-2 marker `i.` is indistinguishable from a paragraph marker once the
document reaches paragraph `1.` again — it is level-2 only when a paragraph is currently
open. A `(i)` note marker collides with `(a)`-style level-3 letters in a document using roman
numeral notes — level-3 only when a level-2 marker is open, and notes are recognised by the
literal 'Note' keyword before the roman marker is considered a note index rather than a
level-3 letter.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from app.corpus.parsers.base import ClauseNode, ParsedInstrument, Parser, para_sort_key

VERSION = "continuous_para/1.0"

_CHAPTER_RE = re.compile(r"^\s*CHAPTER\s+([IVXLCDM]+)\s*[-–—:]?\s*(.*)$")
_SECTION_RE = re.compile(r"^\s*([A-Z])\.\s+(\S.*)$")
_PARA_RE = re.compile(r"^\s*(\d{1,3}[A-Z]?)\.\s+(\S.*)$")
_LEVEL2_ROMAN_RE = re.compile(r"^\s*((?:x{0,3})(?:ix|iv|v?i{0,3}))\.\s+(\S.*)$", re.IGNORECASE)
_LEVEL2_PAREN_NUM_RE = re.compile(r"^\s*\((\d{1,2})\)\s+(\S.*)$")
_LEVEL3_RE = re.compile(r"^\s*\(([a-z])\)\s+(\S.*)$")
_NOTE_RE = re.compile(r"^\s*Note\s*[:.]?\s*(.*)$", re.IGNORECASE)

_ROMAN_VALUES = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
    "xi": 11,
    "xii": 12,
    "xiii": 13,
    "xiv": 14,
    "xv": 15,
}

Dialect = Literal["roman", "paren_numeral"]

# A heading whose presence tags every clause under it as microfinance-scoped. ADR-005 —
# this is what lets the applicability filter express "this clause governs microfinance
# borrowers only" without a per-clause manual pin.
_MICROFINANCE_SECTION_MARKERS = ("microfinance", "MFI conduct", "micro-finance")


@dataclass
class _StackFrame:
    kind: Literal["chapter", "section", "para", "level2", "level3"]
    label: str
    node_index: int | None = None  # index into nodes list, for text accumulation


@dataclass
class _ParserState:
    chapter: str | None = None
    chapter_title: str | None = None
    section_letter: str | None = None
    section_title: str | None = None
    borrower_scope: list[str] = field(default_factory=list)
    stack: list[_StackFrame] = field(default_factory=list)


def _join_hard_wraps(raw_text: str) -> list[str]:
    """Normalise whitespace and join hard-wrapped lines where a line does not end in
    sentence punctuation and the next does not start a new marker."""
    raw_lines = [ln.strip() for ln in raw_text.splitlines()]
    raw_lines = [ln for ln in raw_lines if ln != ""]

    starts_marker = re.compile(
        r"^(CHAPTER\s|[A-Z]\.\s|\d{1,3}[A-Z]?\.\s|\(\d{1,2}\)\s|\([a-z]\)\s|"
        r"(?:x{0,3}(?:ix|iv|v?i{0,3}))\.\s|Note\b)",
        re.IGNORECASE,
    )

    joined: list[str] = []
    for line in raw_lines:
        if (
            joined
            and not joined[-1].rstrip().endswith((".", ":", ";", "?", "!"))
            and not starts_marker.match(line)
        ):
            joined[-1] = joined[-1] + " " + line
        else:
            joined.append(line)
    return joined


class ContinuousParaParser:
    version = VERSION

    def __init__(self, dialect: Dialect):
        self.dialect = dialect
        self._level2_re = _LEVEL2_ROMAN_RE if dialect == "roman" else _LEVEL2_PAREN_NUM_RE

    def parse(self, text: str) -> ParsedInstrument:
        lines = _join_hard_wraps(text)
        nodes: list[ClauseNode] = []
        warnings: list[str] = []
        state = _ParserState()

        order = 0
        last_para_num: int | None = None
        last_level2_val: int | None = None
        chapter_para_count = 0
        open_para_idx: int | None = None
        open_level2_idx: int | None = None

        def current_para_open() -> bool:
            return open_para_idx is not None

        def current_level2_open() -> bool:
            return open_level2_idx is not None

        for line in lines:
            if m := _CHAPTER_RE.match(line):
                if state.chapter is not None and chapter_para_count == 0:
                    warnings.append(f"chapter {state.chapter} has zero paragraphs")
                state.chapter = m.group(1)
                state.chapter_title = m.group(2).strip() or None
                chapter_para_count = 0
                open_para_idx = None
                open_level2_idx = None
                continue

            if m := _SECTION_RE.match(line):
                state.section_letter = m.group(1)
                state.section_title = m.group(2).strip()
                state.borrower_scope = []
                if any(
                    marker.lower() in state.section_title.lower()
                    for marker in _MICROFINANCE_SECTION_MARKERS
                ):
                    state.borrower_scope = ["microfinance"]
                open_para_idx = None
                open_level2_idx = None
                continue

            note_match = _NOTE_RE.match(line) if current_para_open() else None
            level3_match = (
                _LEVEL3_RE.match(line) if current_level2_open() and not note_match else None
            )
            level2_match = (
                self._level2_re.match(line) if current_para_open() and not level3_match else None
            )
            para_match = _PARA_RE.match(line) if not level2_match else None

            if para_match:
                para_number = para_match.group(1)
                body = para_match.group(2)
                para_sort = para_sort_key(para_number)
                if last_para_num is not None and para_sort not in (
                    last_para_num,
                    last_para_num + 1,
                ):
                    warnings.append(
                        f"paragraph {para_number} does not increment by one "
                        f"(previous sort key {last_para_num})"
                    )
                last_para_num = para_sort
                last_level2_val = None
                chapter_para_count += 1

                if len(body) > 4000 and "\n" not in body:
                    warnings.append(
                        f"paragraph {para_number} exceeds 4000 characters with no visible sub-markers yet"
                    )

                node = ClauseNode(
                    chapter=state.chapter,
                    chapter_title=state.chapter_title,
                    section_letter=state.section_letter,
                    section_title=state.section_title,
                    para_number=para_number,
                    para_sort=para_sort,
                    heading=None,
                    text=body,
                    order=order,
                    applies_to_borrower_classes=list(state.borrower_scope),
                )
                nodes.append(node)
                open_para_idx = len(nodes) - 1
                open_level2_idx = None
                order += 1
                continue

            if level2_match:
                label_raw = level2_match.group(1)
                body = level2_match.group(2)
                label = label_raw.lower()
                if self.dialect == "roman":
                    val = _ROMAN_VALUES.get(label)
                    if (
                        val is not None
                        and last_level2_val is not None
                        and val != last_level2_val + 1
                    ):
                        warnings.append(
                            f"level-2 roman sequence skips at '{label_raw}' "
                            f"(previous value {last_level2_val})"
                        )
                    last_level2_val = val
                assert open_para_idx is not None
                parent = nodes[open_para_idx]
                node = ClauseNode(
                    chapter=parent.chapter,
                    chapter_title=parent.chapter_title,
                    section_letter=parent.section_letter,
                    section_title=parent.section_title,
                    para_number=parent.para_number,
                    para_sort=parent.para_sort,
                    level2_label=label,
                    heading=None,
                    text=body,
                    order=order,
                    applies_to_borrower_classes=list(state.borrower_scope),
                )
                nodes.append(node)
                open_level2_idx = len(nodes) - 1
                order += 1
                continue

            if level3_match:
                label = level3_match.group(1)
                body = level3_match.group(2)
                assert open_level2_idx is not None
                parent = nodes[open_level2_idx]
                node = ClauseNode(
                    chapter=parent.chapter,
                    chapter_title=parent.chapter_title,
                    section_letter=parent.section_letter,
                    section_title=parent.section_title,
                    para_number=parent.para_number,
                    para_sort=parent.para_sort,
                    level2_label=parent.level2_label,
                    level3_label=label,
                    heading=None,
                    text=body,
                    order=order,
                    applies_to_borrower_classes=list(state.borrower_scope),
                )
                nodes.append(node)
                order += 1
                continue

            if note_match:
                body = note_match.group(1)
                assert open_para_idx is not None
                parent = nodes[open_para_idx]
                node = ClauseNode(
                    chapter=parent.chapter,
                    chapter_title=parent.chapter_title,
                    section_letter=parent.section_letter,
                    section_title=parent.section_title,
                    para_number=parent.para_number,
                    para_sort=parent.para_sort,
                    level2_label="note",
                    level3_label=str(
                        sum(
                            1
                            for n in nodes
                            if n.para_number == parent.para_number and n.level2_label == "note"
                        )
                        + 1
                    ),
                    heading=None,
                    text=body,
                    order=order,
                    applies_to_borrower_classes=list(state.borrower_scope),
                )
                nodes.append(node)
                order += 1
                continue

            # Continuation of the deepest currently open node — append to its text.
            if nodes:
                nodes[-1].text = (nodes[-1].text + " " + line).strip()

        if state.chapter is not None and chapter_para_count == 0:
            warnings.append(f"chapter {state.chapter} has zero paragraphs")

        para_numbers = [n.para_number for n in nodes if n.level2_label is None]
        detected_range = (para_numbers[0], para_numbers[-1]) if para_numbers else ("", "")

        return ParsedInstrument(
            code="",
            parser_version=self.version,
            nodes=nodes,
            detected_para_range=detected_range,
            warnings=warnings,
        )


def make_parser(dialect: Dialect) -> Parser:
    return ContinuousParaParser(dialect)
