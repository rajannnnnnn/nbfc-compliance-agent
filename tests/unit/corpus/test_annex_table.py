from app.corpus.parsers.annex_table import AnnexTableParser
from app.domain.enums import ChunkKind

ANNEX_FIXTURE = """Sl No    Item    Description
1. Loan proposal / account number    Unique identifier assigned by the lender
2. Type of loan    Personal / gold / vehicle / other
3. Sanctioned amount    Amount sanctioned in the loan agreement, in rupees
Illustration
For a loan of Rs 1,00,000 at 12% p.a. reducing balance repaid over 12 months, the total
interest payable is Rs 6,618.
"""


def test_one_node_per_row_with_headers_prepended():
    parser = AnnexTableParser(part_number="1")
    result = parser.parse(ANNEX_FIXTURE)
    row_nodes = [n for n in result.nodes if n.chunk_kind == ChunkKind.TABLE_ROW]
    assert len(row_nodes) == 3
    for n in row_nodes:
        assert n.text.startswith("Sl No | Item | Description ::")
        assert n.para_number == "annexA"
        assert n.level2_label == "part1"


def test_illustration_stays_whole():
    parser = AnnexTableParser(part_number="1")
    result = parser.parse(ANNEX_FIXTURE)
    illustrations = [n for n in result.nodes if n.chunk_kind == ChunkKind.ILLUSTRATION]
    assert len(illustrations) == 1
    assert "6,618" in illustrations[0].text


def test_row_numbers_become_level3_label():
    parser = AnnexTableParser(part_number="2")
    result = parser.parse(ANNEX_FIXTURE)
    row_nodes = [n for n in result.nodes if n.chunk_kind == ChunkKind.TABLE_ROW]
    labels = [n.level3_label for n in row_nodes]
    assert labels == ["1", "2", "3"]


def test_node_count_equals_row_count_plus_illustrations():
    parser = AnnexTableParser()
    result = parser.parse(ANNEX_FIXTURE)
    assert len(result.nodes) == 4  # 3 rows + 1 illustration
