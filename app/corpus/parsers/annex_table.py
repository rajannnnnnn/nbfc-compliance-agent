"""Tabular annex parser (KFS Annex A). LLD §6.2: one node per row, headers prepended to each
row's text. Worked numeric illustrations parse as a single whole node, chunk_kind='illustration'.

Input format (plain-text extraction of the annex table): a header line, then one line per row,
tab- or multi-space-separated. A row beginning "Illustration" (case-insensitive) and everything
until the next row marker is captured as a single illustration node instead of being split.
"""

import re

from app.corpus.parsers.base import ClauseNode, ParsedInstrument
from app.domain.enums import ChunkKind

_CELL_SPLIT_RE = re.compile(r"\t+|\s{2,}")
_ROW_MARKER_RE = re.compile(r"^\s*(\d{1,2})[.)]\s+")
_ILLUSTRATION_START_RE = re.compile(r"^\s*Illustration\b", re.IGNORECASE)


class AnnexTableParser:
    version = "annex_table/1.0"

    def __init__(self, part_number: str = "1"):
        self.part_number = part_number

    def parse(self, text: str) -> ParsedInstrument:
        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return ParsedInstrument(
                code="",
                parser_version=self.version,
                nodes=[],
                detected_para_range=("", ""),
                warnings=["annex text is empty"],
            )

        header_cells = [c.strip() for c in _CELL_SPLIT_RE.split(lines[0]) if c.strip()]
        header_prefix = " | ".join(header_cells)

        nodes: list[ClauseNode] = []
        warnings: list[str] = []
        order = 0
        i = 1
        row_seq = 0

        while i < len(lines):
            line = lines[i]
            if _ILLUSTRATION_START_RE.match(line):
                block = [line]
                i += 1
                while (
                    i < len(lines)
                    and not _ROW_MARKER_RE.match(lines[i])
                    and not _ILLUSTRATION_START_RE.match(lines[i])
                ):
                    block.append(lines[i])
                    i += 1
                nodes.append(
                    ClauseNode(
                        para_number="annexA",
                        para_sort=0,
                        level2_label=f"part{self.part_number}",
                        level3_label="illustration",
                        heading="Worked illustration",
                        text=" ".join(block),
                        order=order,
                        chunk_kind=ChunkKind.ILLUSTRATION,
                    )
                )
                order += 1
                continue

            m = _ROW_MARKER_RE.match(line)
            if not m:
                warnings.append(f"unrecognised annex line skipped: {line[:60]!r}")
                i += 1
                continue

            row_seq += 1
            row_number = m.group(1)
            row_text = line[m.end() :].strip()
            nodes.append(
                ClauseNode(
                    para_number="annexA",
                    para_sort=0,
                    level2_label=f"part{self.part_number}",
                    level3_label=row_number,
                    heading=None,
                    text=f"{header_prefix} :: {row_text}",
                    order=order,
                    chunk_kind=ChunkKind.TABLE_ROW,
                )
            )
            order += 1
            i += 1

        return ParsedInstrument(
            code="",
            parser_version=self.version,
            nodes=nodes,
            detected_para_range=("annexA", "annexA"),
            warnings=warnings,
        )
