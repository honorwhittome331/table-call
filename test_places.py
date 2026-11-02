"""Unit tests for opening-hours filtering and ranking. Run: python -m pytest -q"""
from datetime import datetime

from places import is_open_for_sitting, score, time_window

TUE_1930 = datetime(2026, 11, 3, 19, 30)  # a Tuesday


def hours(*periods):
    return {"periods": [
        {"open": {"day": d1, "hour": h1, "minute": 0}, "close": {"day": d2, "hour": h2, "minute": 0}}
        for d1, h1, d2, h2 in periods
    ]}


def test_open_in_evening_slot():
    assert is_open_for_sitting(hours((2, 17, 2, 22)), TUE_1930)


def test_closes_too_soon():
    assert not is_open_for_sitting(hours((2, 12, 2, 20)), TUE_1930)


def test_closed_that_day():
    assert not is_open_for_sitting(hours((3, 17, 3, 22)), TUE_1930)


def test_open_past_midnight():
    assert is_open_for_sitting(hours((2, 18, 3, 1)), TUE_1930)


def test_saturday_into_sunday_wrap():
    sat_2330 = datetime(2026, 11, 7, 23, 30)
    assert is_open_for_sitting(hours((6, 18, 0, 2)), sat_2330)


def test_open_24_hours():
    assert is_open_for_sitting({"periods": [{"open": {"day": 0, "hour": 0, "minute": 0}}]}, TUE_1930)


def test_bayesian_ranking_prefers_many_reviews():
    few = {"rating": 4.9, "rating_count": 8}
    many = {"rating": 4.6, "rating_count": 900}
    assert score(many) > score(few)


def test_time_window():
    early, late = time_window(TUE_1930, 45)
    assert (early.hour, early.minute, late.hour, late.minute) == (18, 45, 20, 15)
