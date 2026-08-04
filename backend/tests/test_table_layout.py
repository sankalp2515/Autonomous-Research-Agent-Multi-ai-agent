"""Regression tests for the adaptive comparison-table validator.

Live QA caught a model emitting the SAME finding index in every column, which
rendered a table with the identical sentence repeated across each cell. These
pin the validation that prevents it.
"""

from app.agents.nodes import build_table_layout

COLS = ["Approach", "Mechanism", "Goal"]


def test_duplicate_index_across_columns_is_dropped():
    # The real bug: index 0 repeated in all three columns of a row.
    rows = [("VLA", {"Approach": [0], "Mechanism": [0], "Goal": [0]}),
            ("MoPAC", {"Approach": [1], "Mechanism": [1], "Goal": [1]})]
    layout = build_table_layout(COLS, rows, n=4)
    # Only one column survives per row -> not a real grid -> prose fallback.
    assert layout is None


def test_valid_grid_is_kept():
    rows = [("VLA", {"Approach": [0], "Mechanism": [1]}),
            ("MoPAC", {"Approach": [2], "Mechanism": [3]})]
    layout = build_table_layout(COLS, rows, n=4)
    assert layout is not None
    assert layout["kind"] == "table"
    assert layout["columns"] == ["Approach", "Mechanism"]  # empty "Goal" dropped
    assert len(layout["rows"]) == 2


def test_each_index_used_at_most_once_across_the_table():
    rows = [("A", {"Approach": [0], "Mechanism": [1]}),
            ("B", {"Approach": [0], "Mechanism": [2]})]  # 0 reused in row B
    layout = build_table_layout(COLS, rows, n=3)
    assert layout is not None
    used = [i for r in layout["rows"] for idxs in r["cells"].values() for i in idxs]
    assert sorted(used) == [0, 1, 2]           # no duplicates
    assert 0 not in layout["rows"][1]["cells"].get("Approach", [])


def test_out_of_range_indices_ignored():
    rows = [("A", {"Approach": [0], "Mechanism": [99]}),
            ("B", {"Approach": [1], "Mechanism": [2]})]
    layout = build_table_layout(COLS, rows, n=3)
    assert layout is not None
    used = [i for r in layout["rows"] for idxs in r["cells"].values() for i in idxs]
    assert 99 not in used


def test_single_row_falls_back_to_prose():
    rows = [("only", {"Approach": [0], "Mechanism": [1]})]
    assert build_table_layout(COLS, rows, n=2) is None


def test_empty_or_malformed_cells_are_safe():
    rows = [("A", {}), ("B", None)]  # type: ignore[arg-type]
    assert build_table_layout(COLS, rows, n=2) is None
