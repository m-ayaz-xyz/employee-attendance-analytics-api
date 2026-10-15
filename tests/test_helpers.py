import pytest
from datetime import date, datetime, timezone

from fastapi import HTTPException

from app.main import (
    as_utc,
    compute_work_hours,
    month_bounds,
    normalize_aggregation,
    parse_hhmm,
    round_num,
    validate_date,
    validate_month,
)


def test_parse_hhmm_accepts_valid_time():
    assert parse_hhmm("09:30") == (9, 30)
    assert parse_hhmm("23:59") == (23, 59)


@pytest.mark.parametrize("value", ["9:30", "24:00", "12:60", "abc", "", None])
def test_parse_hhmm_rejects_invalid_time(value):
    with pytest.raises(HTTPException) as exc:
        parse_hhmm(value)
    assert exc.value.status_code == 422


def test_validate_date_accepts_iso_date():
    assert validate_date("2026-10-15") == date(2026, 10, 15)


@pytest.mark.parametrize("value", ["15-10-2026", "2026-2-01", "2026-02-30", ""])
def test_validate_date_rejects_invalid_date(value):
    with pytest.raises(HTTPException) as exc:
        validate_date(value)
    assert exc.value.status_code == 422


def test_validate_month_returns_first_and_last_day():
    start, end = validate_month("2024-02")
    assert start == date(2024, 2, 1)
    assert end == date(2024, 2, 29)


@pytest.mark.parametrize("value", ["2026-00", "2026-13", "26-10", "2026/10", ""])
def test_validate_month_rejects_invalid_month(value):
    with pytest.raises(HTTPException) as exc:
        validate_month(value)
    assert exc.value.status_code == 422


def test_month_bounds_returns_strings_and_dates():
    start_s, end_s, start, end = month_bounds("2026-10")
    assert start_s == "2026-10-01"
    assert end_s == "2026-10-31"
    assert start == date(2026, 10, 1)
    assert end == date(2026, 10, 31)


def test_compute_work_hours():
    start = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 15, 17, 30, tzinfo=timezone.utc)
    assert compute_work_hours(start, end) == 8.5


def test_as_utc_adds_timezone_to_naive_datetime():
    result = as_utc(datetime(2026, 10, 15, 9, 0))
    assert result.tzinfo == timezone.utc
    assert result.hour == 9


def test_round_num():
    assert round_num(12.345, 2) == 12.35
    assert round_num(12.5, 0) == 13.0
    assert round_num(None, 2) is None


def test_normalize_aggregation_converts_nested_datetimes():
    value = {
        "created": datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc),
        "nested": [{"date": datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)}],
    }
    result = normalize_aggregation(value)
    expected_9 = int(datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc).timestamp() * 1000)
    expected_10 = int(datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert result["created"] == expected_9
    assert result["nested"][0]["date"] == expected_10
