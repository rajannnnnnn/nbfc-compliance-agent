from app.corpus.parsers.base import ClauseNode
from app.corpus.references import CIRCULAR_RE, extract_references

KNOWN = {
    "KFS2024": [
        r"Key Facts Statement \(KFS\) for Loans\s*&?\s*Advances",
        r"Key Facts Statement circular",
    ]
}


def test_circular_re_matches_real_number():
    m = CIRCULAR_RE.search("as per RBI/2024-25/18 DOR.STR.REC.13/13.03.00/2024-25")
    assert m is not None
    assert m.group(1) == "DOR.STR.REC.13/13.03.00/2024-25"


def test_circular_re_rejects_near_miss():
    m = CIRCULAR_RE.search("DOR.STR.NOTAREC.13/13.03.00/2024-25")
    assert m is None


def test_incorporates_kfs_from_dl2025():
    node = ClauseNode(
        para_number="8",
        level2_label="i",
        para_sort=8,
        order=0,
        text=(
            "The regulated entity shall ensure that the Key Facts Statement is issued in "
            "terms of instructions contained in the Key Facts Statement circular before "
            "execution of the loan agreement."
        ),
    )
    edges = extract_references([node], KNOWN)
    assert len(edges) == 1
    assert edges[0].from_clause_path == "p8/i"
    assert edges[0].to_instrument_code == "KFS2024"
    assert edges[0].reference_kind == "incorporates"


def test_repeal_paragraph_detected():
    node = ClauseNode(
        para_number="2",
        para_sort=2,
        order=0,
        text="The Guidelines on Digital Lending under DOR.CRE.REC.66/21.07.001/2022-23 stand repealed.",
    )
    edges = extract_references([node], {"LEGACY2022": [r"Guidelines on Digital Lending"]})
    assert edges[0].reference_kind == "repeals"


def test_amends_when_instrument_is_amendment():
    node = ClauseNode(
        para_number="1",
        para_sort=1,
        order=0,
        text="This amends the Responsible Business Conduct Directions in respect of recovery agents.",
    )
    edges = extract_references(
        [node], {"RBC2025": [r"Responsible Business Conduct"]}, instrument_is_amendment=True
    )
    assert edges[0].reference_kind == "amends"


def test_see_also_default():
    node = ClauseNode(
        para_number="5",
        para_sort=5,
        order=0,
        text="See also the Key Facts Statement (KFS) for Loans & Advances circular for the field list.",
    )
    edges = extract_references([node], KNOWN)
    assert edges[0].reference_kind == "see_also"
