"""Leaf-clause chunking with stem prepending. LLD §6.3.

A bare `(a) thirty days;` embedded alone is unretrievable and, worse, retrievable for the
wrong query. The stem — the parent node's first sentence, truncated to 200 characters — is
what makes it mean something.
"""

import re

from pydantic import BaseModel

from app.corpus.parsers.base import ClauseNode
from app.domain.enums import ChunkKind

STEM_MIN_TOKENS = 40
STEM_MAX_CHARS = 200

_SENTENCE_END_RE = re.compile(r"[.!?](?:\s|$)")


def _token_count(text: str) -> int:
    return len(text.split())


def _first_sentence(text: str) -> str:
    m = _SENTENCE_END_RE.search(text)
    sentence = text[: m.end()].strip() if m else text
    return sentence[:STEM_MAX_CHARS]


class ClauseChunk(BaseModel):
    node: ClauseNode
    text_with_stem: str
    token_count: int
    chunk_strategy: str
    chunk_index: int


def chunk(
    nodes: list[ClauseNode], *, parent_index: dict[int, ClauseNode] | None = None
) -> list[ClauseChunk]:
    """One chunk per node. `parent_index` maps a node's list index to its immediate parent
    node (built by the caller from the stack context during parsing, or reconstructed here
    from para_number/level2_label/level3_label adjacency for nodes parsed independently)."""
    chunks: list[ClauseChunk] = []

    # Build a parent lookup by structural key when not supplied: a level3 node's parent is
    # the level2 node with the same (para_number, level2_label); a level2 node's parent is
    # the para node with the same para_number and no level2_label.
    by_key: dict[tuple[str, str | None, str | None], ClauseNode] = {}
    for n in nodes:
        key = (n.para_number, n.level2_label, n.level3_label)
        by_key[key] = n

    def parent_of(n: ClauseNode) -> ClauseNode | None:
        if n.level3_label is not None:
            return by_key.get((n.para_number, n.level2_label, None))
        if n.level2_label is not None:
            return by_key.get((n.para_number, None, None))
        return None

    for idx, node in enumerate(nodes):
        if node.chunk_kind == ChunkKind.ILLUSTRATION:
            chunks.append(
                ClauseChunk(
                    node=node,
                    text_with_stem=node.text,
                    token_count=_token_count(node.text),
                    chunk_strategy="illustration_whole",
                    chunk_index=idx,
                )
            )
            continue
        if node.chunk_kind == ChunkKind.TABLE_ROW:
            chunks.append(
                ClauseChunk(
                    node=node,
                    text_with_stem=node.text,
                    token_count=_token_count(node.text),
                    chunk_strategy="table_row",
                    chunk_index=idx,
                )
            )
            continue

        tcount = _token_count(node.text)
        if tcount < STEM_MIN_TOKENS:
            parent = parent_of(node)
            if parent is not None:
                stem = _first_sentence(parent.text)
                text_with_stem = f"{stem} {node.text}".strip()
                strategy = "leaf+stem"
            else:
                text_with_stem = node.text
                strategy = "leaf"
        else:
            text_with_stem = node.text
            strategy = "leaf"

        chunks.append(
            ClauseChunk(
                node=node,
                text_with_stem=text_with_stem,
                token_count=tcount,
                chunk_strategy=strategy,
                chunk_index=idx,
            )
        )

    return chunks
