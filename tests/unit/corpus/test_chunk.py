from app.corpus.chunk import STEM_MIN_TOKENS, chunk
from app.corpus.parsers.base import ClauseNode
from app.domain.enums import ChunkKind


def _para(text: str, order: int) -> ClauseNode:
    return ClauseNode(para_number="9", para_sort=9, text=text, order=order)


def _level2(text: str, order: int, label: str = "i") -> ClauseNode:
    return ClauseNode(para_number="9", para_sort=9, level2_label=label, text=text, order=order)


def test_short_leaf_gets_stem_prepended():
    parent_text = "Disbursal and repayment requirements for digital lending. " + "word " * 50
    parent = _para(parent_text, 0)
    short_child = _level2("thirty days.", 1)  # well under STEM_MIN_TOKENS
    chunks = chunk([parent, short_child])
    child_chunk = chunks[1]
    assert child_chunk.chunk_strategy == "leaf+stem"
    assert child_chunk.text_with_stem.startswith(
        "Disbursal and repayment requirements for digital lending."
    )
    assert "thirty days." in child_chunk.text_with_stem


def test_long_leaf_has_no_stem():
    parent = _para("Short parent.", 0)
    long_text = " ".join(["word"] * (STEM_MIN_TOKENS + 5))
    long_child = _level2(long_text, 1)
    chunks = chunk([parent, long_child])
    child_chunk = chunks[1]
    assert child_chunk.chunk_strategy == "leaf"
    assert child_chunk.text_with_stem == long_text


def test_stem_truncated_to_200_chars():
    long_first_sentence = "A" * 300 + "."
    parent = _para(long_first_sentence, 0)
    short_child = _level2("short.", 1)
    chunks = chunk([parent, short_child])
    stem_part = chunks[1].text_with_stem.split(" short.")[0]
    assert len(stem_part) <= 200


def test_table_row_and_illustration_keep_their_strategy():
    row = ClauseNode(
        para_number="annexA",
        para_sort=0,
        level3_label="1",
        text="header :: value",
        order=0,
        chunk_kind=ChunkKind.TABLE_ROW,
    )
    illus = ClauseNode(
        para_number="annexA",
        para_sort=0,
        level3_label="illustration",
        text="worked example",
        order=1,
        chunk_kind=ChunkKind.ILLUSTRATION,
    )
    chunks = chunk([row, illus])
    assert chunks[0].chunk_strategy == "table_row"
    assert chunks[1].chunk_strategy == "illustration_whole"


def test_chunk_count_equals_node_count():
    nodes = [_para("one two three", 0), _level2("a b c", 1), _level2("d e f", 2, label="ii")]
    chunks = chunk(nodes)
    assert len(chunks) == len(nodes)
