from app.corpus.parsers.continuous_para import ContinuousParaParser

DL2025_FIXTURE = """
CHAPTER I - PRELIMINARY

1. Short title and commencement. These Directions shall be called the Reserve Bank of
India (Digital Lending) Directions, 2025.

CHAPTER III - CONDUCT REQUIREMENTS

8. Disclosure requirements.
i. The regulated entity shall ensure that the Key Facts Statement is issued in terms of
instructions contained in the Key Facts Statement circular before execution of the loan
agreement.
ii. The Annual Percentage Rate shall be disclosed in the Key Facts Statement.

9. Disbursal and repayment.
i. All loan disbursals shall be made directly into the bank account of the borrower.
ii. All repayments shall be collected back only into the bank account of the regulated
entity, without any pass-through account of the lending service provider.

10. Cooling-off period.
The borrower shall be given an explicit option to exit the digital loan by paying the
principal and proportionate charges without penalty during the cooling-off period.
Note: The cooling-off period shall not be less than one day.
"""

RBC2025_FIXTURE = """
CHAPTER IV - FAIR PRACTICE IN RECOVERY

30. Penal charges.
(1) Penal charges shall not be levied in the form of penal interest added to the rate of
interest charged on the advance.
(2) Penal charges shall not be capitalised.

35. Release of documents. The regulated entity shall release all original movable or
immovable property documents within a period of 30 days after full repayment of the loan.

H. Microfinance conduct requirements

45. Contact hours for microfinance borrowers.
(1) Recovery agents shall not contact microfinance borrowers otherwise than between 0800
hours and 1900 hours.
"""


def test_dl2025_golden_nodes():
    parser = ContinuousParaParser(dialect="roman")
    result = parser.parse(DL2025_FIXTURE)
    # The fixture deliberately skips paragraphs 2-7 for brevity — the parser is right to warn
    # about the gap (real-corpus ingest would fail on an unexplained gap, per M1-T03's
    # acceptance: "warnings list empty or explained in the report").
    assert result.warnings == ["paragraph 8 does not increment by one (previous sort key 1)"]

    paths = [n.clause_path for n in result.nodes]
    assert "p1" in paths
    assert "p8" in paths
    assert "p8/i" in paths
    assert "p8/ii" in paths
    assert "p9" in paths
    assert "p9/i" in paths
    assert "p9/ii" in paths
    assert "p10" in paths

    n8 = next(n for n in result.nodes if n.clause_path == "p8")
    assert n8.chapter == "III"
    assert n8.chapter_title == "CONDUCT REQUIREMENTS"

    n8i = next(n for n in result.nodes if n.clause_path == "p8/i")
    assert "Key Facts Statement" in n8i.text
    # parent text must not duplicate child text
    assert n8i.text not in n8.text


def test_dl2025_note_after_paragraph():
    parser = ContinuousParaParser(dialect="roman")
    result = parser.parse(DL2025_FIXTURE)
    note_nodes = [n for n in result.nodes if n.level2_label == "note"]
    assert len(note_nodes) == 1
    assert "one day" in note_nodes[0].text
    assert note_nodes[0].para_number == "10"


def test_rbc2025_paren_numeral_dialect():
    parser = ContinuousParaParser(dialect="paren_numeral")
    result = parser.parse(RBC2025_FIXTURE)
    paths = [n.clause_path for n in result.nodes]
    assert "p30/1" in paths
    assert "p30/2" in paths
    assert "p35" in paths
    assert "p45/1" in paths


def test_rbc2025_microfinance_section_tags_borrower_scope():
    parser = ContinuousParaParser(dialect="paren_numeral")
    result = parser.parse(RBC2025_FIXTURE)
    n45 = next(n for n in result.nodes if n.para_number == "45" and n.level2_label is None)
    assert n45.applies_to_borrower_classes == ["microfinance"]
    n35 = next(n for n in result.nodes if n.para_number == "35")
    assert n35.applies_to_borrower_classes == []


def test_100w_sorts_between_100a_and_101():
    parser = ContinuousParaParser(dialect="paren_numeral")
    text = "100A. First.\n\n100W. Second.\n\n101. Third.\n"
    result = parser.parse(text)
    by_num = {n.para_number: n.para_sort for n in result.nodes}
    ordering = sorted(result.nodes, key=lambda n: (n.para_sort, n.para_number))
    assert [n.para_number for n in ordering] == ["100A", "100W", "101"]
    assert by_num["100A"] == by_num["100W"] == 100
    assert by_num["101"] == 101


def test_paragraph_number_skip_warns_not_raises():
    parser = ContinuousParaParser(dialect="roman")
    text = "1. First paragraph.\n\n5. Skipped ahead.\n"
    result = parser.parse(text)
    assert any("does not increment" in w for w in result.warnings)
    assert len(result.nodes) == 2  # warns, never fails


def test_chapter_with_zero_paragraphs_warns():
    parser = ContinuousParaParser(dialect="roman")
    text = "CHAPTER I - EMPTY\n\nCHAPTER II - HAS CONTENT\n\n1. A paragraph.\n"
    result = parser.parse(text)
    assert any("CHAPTER I" in w or "chapter I" in w for w in result.warnings) or any(
        "zero paragraphs" in w for w in result.warnings
    )


def test_roman_level2_only_recognised_when_paragraph_open():
    """A lower-roman marker before any paragraph is open must not be misread as level-2."""
    parser = ContinuousParaParser(dialect="roman")
    text = "CHAPTER I - TITLE\n\ni. This is not a sub-clause, no paragraph is open yet.\n"
    result = parser.parse(text)
    # With no paragraph open, the line is neither a valid para (doesn't match \d+\.) nor a
    # valid level-2 (guarded by current_para_open()) — it is treated as a continuation line
    # and produces no nodes at all, which is the correct, safe behaviour.
    assert not any(n.level2_label == "i" for n in result.nodes)


def test_letter_level3_only_recognised_when_level2_open():
    parser = ContinuousParaParser(dialect="roman")
    text = "1. Paragraph text.\n(a) This should not become a level-3 without an open level-2.\n"
    result = parser.parse(text)
    assert not any(n.level3_label == "a" for n in result.nodes)


def test_parent_text_excludes_children_text():
    parser = ContinuousParaParser(dialect="roman")
    result = parser.parse(DL2025_FIXTURE)
    n9 = next(n for n in result.nodes if n.clause_path == "p9")
    n9i = next(n for n in result.nodes if n.clause_path == "p9/i")
    n9ii = next(n for n in result.nodes if n.clause_path == "p9/ii")
    assert n9i.text not in n9.text
    assert n9ii.text not in n9.text
