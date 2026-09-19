from app.corpus.pinning import expand_parent_to_descendants, load_pinning_yaml

REAL_PATH = "app/corpus/pinning.yaml"


def test_loads_real_pinning_file():
    pins = load_pinning_yaml(REAL_PATH)
    assert "apr_bps" in pins
    assert "RBC2025/p29" in pins["apr_bps"]
    assert "contact_datetime" in pins


def test_expand_parent_includes_self_and_descendants():
    all_paths = ["RBC2025/p35", "RBC2025/p35/1", "RBC2025/p35/1/a", "RBC2025/p36", "RBC2025/p350"]
    expanded = expand_parent_to_descendants("RBC2025/p35", all_paths)
    assert set(expanded) == {"RBC2025/p35", "RBC2025/p35/1", "RBC2025/p35/1/a"}
    # RBC2025/p350 must NOT match as a descendant of p35 (prefix must be followed by '/')
    assert "RBC2025/p350" not in expanded


def test_expand_leaf_with_no_children_returns_only_itself():
    all_paths = ["RBC2025/p29", "RBC2025/p30"]
    assert expand_parent_to_descendants("RBC2025/p29", all_paths) == ["RBC2025/p29"]
