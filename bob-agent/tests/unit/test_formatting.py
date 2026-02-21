"""Unit tests for app/utils/formatting.py — pure functions, no external deps."""

from unittest.mock import MagicMock

import pytest

from app.utils.formatting import filter_defects, format_defect_row, parse_id_filter


def _defect(defect_id=1, description="crack", supplier="ספק א", location="קומה 1", status="פתוח"):
    d = MagicMock()
    d.defect_id = defect_id
    d.description = description
    d.supplier = supplier
    d.location = location
    d.status = status
    return d


# ---------------------------------------------------------------------------
# format_defect_row
# ---------------------------------------------------------------------------


def test_format_defect_row_all_fields():
    d = _defect(defect_id=5, description="water leak", supplier="ספק א", location="קומה 1", status="פתוח")
    row = format_defect_row(d)
    assert "#5" in row
    assert "water leak" in row
    assert "ספק א" in row
    assert "קומה 1" in row
    assert "[פתוח]" in row


def test_format_defect_row_no_location_no_supplier():
    d = _defect(description="damp wall", supplier="", location="")
    row = format_defect_row(d)
    assert "damp wall" in row
    assert "#1" in row
    # empty supplier/location should not appear as separate segments
    parts = row.split(" | ")
    assert "" not in parts


def test_format_defect_row_separator():
    d = _defect()
    row = format_defect_row(d)
    assert " | " in row


# ---------------------------------------------------------------------------
# parse_id_filter
# ---------------------------------------------------------------------------


def test_parse_id_filter_range():
    assert parse_id_filter("77-80") == {77, 78, 79, 80}


def test_parse_id_filter_single_range():
    assert parse_id_filter("5-5") == {5}


def test_parse_id_filter_comma():
    assert parse_id_filter("5,7,12") == {5, 7, 12}


def test_parse_id_filter_single():
    assert parse_id_filter("3") == {3}


def test_parse_id_filter_with_spaces():
    assert parse_id_filter("1, 2, 3") == {1, 2, 3}


def test_parse_id_filter_range_with_spaces():
    assert parse_id_filter("10 - 12") == {10, 11, 12}


# ---------------------------------------------------------------------------
# filter_defects
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_defects():
    return [
        _defect(defect_id=1, description="crack in wall", supplier="ספק א", location="קומה 1", status="פתוח"),
        _defect(defect_id=2, description="water leak", supplier="ספק ב", location="קומה 2", status="בעבודה"),
        _defect(defect_id=3, description="broken window", supplier="ספק א", location="קומה 1", status="סגור"),
        _defect(defect_id=4, description="crack in floor", supplier="ספק ג", location="קומה 3", status="פתוח"),
    ]


def test_filter_no_filters(sample_defects):
    result = filter_defects(sample_defects)
    assert len(result) == 4


def test_filter_by_status(sample_defects):
    result = filter_defects(sample_defects, status_filter="פתוח")
    assert len(result) == 2
    assert all(d.status == "פתוח" for d in result)


def test_filter_by_description(sample_defects):
    result = filter_defects(sample_defects, description_filter="crack")
    assert len(result) == 2
    assert all("crack" in d.description for d in result)


def test_filter_by_description_case_insensitive(sample_defects):
    result = filter_defects(sample_defects, description_filter="CRACK")
    assert len(result) == 2


def test_filter_by_supplier(sample_defects):
    result = filter_defects(sample_defects, supplier_filter="ספק א")
    assert len(result) == 2
    assert all(d.supplier == "ספק א" for d in result)


def test_filter_by_defect_id_range(sample_defects):
    result = filter_defects(sample_defects, defect_id_filter="1-3")
    assert {d.defect_id for d in result} == {1, 2, 3}


def test_filter_by_defect_id_comma(sample_defects):
    result = filter_defects(sample_defects, defect_id_filter="1,4")
    assert {d.defect_id for d in result} == {1, 4}


def test_filter_combined(sample_defects):
    result = filter_defects(sample_defects, status_filter="פתוח", supplier_filter="ספק א")
    assert len(result) == 1
    assert result[0].defect_id == 1


def test_filter_no_match(sample_defects):
    result = filter_defects(sample_defects, status_filter="ארכיון")
    assert result == []
