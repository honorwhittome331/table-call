"""Unit tests for group preference handling and group-fit ranking. Run: python -m pytest -q"""
from datetime import datetime
from unittest.mock import patch

import group

PEOPLE = group.normalise({"people": [
    {"label": "Amy", "likes": ["Thai", "italian"], "dislikes": [], "needs": []},
    {"label": "Ben", "likes": ["thai"], "dislikes": ["indian"], "needs": []},
    {"label": "Sam", "likes": ["italian", "indian"], "dislikes": [], "needs": ["vegan"]},
]})["people"]


def test_normalise_lowercases_and_infers_party_size():
    prefs = group.normalise({"people": [{"likes": [" Thai "]}, {}]})
    assert prefs["party_size"] == 2
    assert prefs["people"][0]["likes"] == ["thai"]
    assert prefs["people"][1]["label"] == "Person 2"


def test_vetoed_cuisine_excluded_and_popular_first():
    assert group.candidate_cuisines(PEOPLE) == ["italian", "thai"]  # indian vetoed by Ben


def test_group_fit():
    assert group.group_fit("thai", PEOPLE) == 2 / 3
    assert group.group_fit("", PEOPLE) == 0.5


def test_needs_note():
    assert group.needs_note(PEOPLE) == "vegan"


def test_parse_json_with_fences():
    assert group.parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_normalise_survives_messy_model_output():
    prefs = group.normalise([{
        "party_size": "4", "time": "7:30", "date": "tomorrow", "flex_minutes": "thirty",
        "min_rating": "4.5", "max_price_level": None,
        "people": [{"label": "Amy", "likes": "Thai", "dislikes": None, "needs": [None, "vegan", {"x": 1}]}, "junk"],
    }])
    assert prefs["party_size"] == 4
    assert prefs["time"] == "07:30"
    assert prefs["date"] is None           # not YYYY-MM-DD, so the form value is used
    assert prefs["flex_minutes"] is None
    assert prefs["min_rating"] == 4.5
    assert prefs["people"] == [{"label": "Amy", "likes": ["thai"], "dislikes": [], "needs": ["vegan"]}]


def test_gemini_timeout_is_retried():
    import requests as rq
    replies = [rq.Timeout("slow"), FakeResp(200)]
    def fake_post(url, **kw):
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    with patch("group.requests.post", side_effect=fake_post), patch("group.time.sleep"):
        assert group.call_gemini("k", "gemini-flash-latest", {}).status_code == 200


class FakeResp:
    def __init__(self, code):
        self.status_code, self.text = code, "{}"


def test_gemini_falls_back_when_busy():
    calls = []
    def fake_post(url, **kw):
        calls.append(url.split("/models/")[1].split(":")[0])
        return FakeResp(200 if "models/gemini-2.5-flash:" in url else 503)
    with patch("group.requests.post", side_effect=fake_post), patch("group.time.sleep"):
        resp = group.call_gemini("k", "gemini-2.5-flash-lite", {})
    assert resp.status_code == 200
    assert calls == ["gemini-2.5-flash-lite", "gemini-2.5-flash-lite",
                     "gemini-flash-lite-latest", "gemini-flash-lite-latest", "gemini-2.5-flash"]


def test_gemini_bad_key_stops_immediately():
    with patch("group.requests.post", return_value=FakeResp(403)) as p:
        try:
            group.call_gemini("bad", "gemini-flash-latest", {})
        except RuntimeError as e:
            assert "403" in str(e)
    assert p.call_count == 1


def test_rank_prefers_group_fit_and_respects_budget():
    fake = {
        "italian": [
            {"id": "i1", "name": "Pasta", "rating": 4.5, "rating_count": 400, "price_level": "PRICE_LEVEL_MODERATE"},
            {"id": "i2", "name": "Posh", "rating": 4.9, "rating_count": 900, "price_level": "PRICE_LEVEL_VERY_EXPENSIVE"},
        ],
        "thai": [
            {"id": "t1", "name": "Thai Gold", "rating": 4.6, "rating_count": 400, "price_level": None},
        ],
    }
    prefs = {"people": PEOPLE, "max_price_level": 2}
    with patch("group.search_restaurants", side_effect=lambda k, c, *a, **kw: fake[c]):
        ranked = group.rank_for_group("key", prefs, datetime(2026, 11, 3, 19, 30), "Oxford", 4.0)
    names = [r["name"] for r in ranked]
    assert "Posh" not in names            # over budget
    assert set(names) == {"Pasta", "Thai Gold"}
    assert "wanted by 2 of 3" in ranked[0]["reason"]
