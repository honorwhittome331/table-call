"""Group mode: understand a group's dinner conversation and rank restaurants by group fit.

1. extract_preferences(): Gemini reads the transcript and returns structured preferences.
2. rank_for_group(): searches Places for each acceptable cuisine and scores every
   restaurant by how well it suits the whole group, with a plain-English reason.
"""
import json
import re
import time
from datetime import date

import requests

from places import score as rating_score, search_restaurants

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}

# How much group fit matters versus rating in the final score (must sum to 1).
FIT_WEIGHT = 0.6
RATING_WEIGHT = 0.4
MAX_CUISINES = 3

EXTRACTION_PROMPT = """You are listening to a group of friends deciding where to eat dinner.
The transcript comes from speech recognition, so it has no speaker labels and may contain errors.
Infer the separate people from context (names, "I", "me", disagreements). If unclear, make your best estimate.

Today is {today}. Default area: {area}.

Return ONLY a JSON object with exactly these keys:
{{
  "party_size": integer or null,
  "date": "YYYY-MM-DD" or null (resolve words like "tomorrow" or "Friday" using today's date),
  "time": "HH:MM" 24-hour or null,
  "flex_minutes": integer or null (how flexible they are on time, e.g. "around 7" = 30),
  "people": [
    {{"label": "name if mentioned, else Person 1, Person 2...",
      "likes": ["cuisines they want or are happy with"],
      "dislikes": ["cuisines they rejected or vetoed"],
      "needs": ["dietary or access needs, e.g. vegan, gluten-free, wheelchair access"]}}
  ],
  "max_price_level": integer 1-4 or null (1 = cheap, 4 = very expensive; only if budget was discussed),
  "min_rating": number or null (only if quality was explicitly discussed),
  "summary": "one sentence describing what the group wants"
}}

Rules:
- Use simple, searchable cuisine names in lower case: "thai", "italian", "indian", "pizza", "sushi", "burger", "mexican", "chinese", "vegan".
- A strong objection ("not Indian again", "I can't do spicy food") counts as a dislike.
- Lukewarm acceptance ("I could do Thai I suppose") counts as a like.
- Do not invent preferences that were not expressed.

Transcript:
\"\"\"{transcript}\"\"\"
"""


def extract_preferences(api_key, model, transcript, area="Oxford, UK", today=None):
    """Ask Gemini to turn a free-form transcript into structured preferences."""
    if not transcript or not transcript.strip():
        raise ValueError("The transcript is empty.")
    prompt = EXTRACTION_PROMPT.format(
        today=(today or date.today()).strftime("%A %d %B %Y (%Y-%m-%d)"),
        area=area,
        transcript=transcript.strip()[:8000],
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }
    resp = call_gemini(api_key, model, body)
    try:
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise RuntimeError(f"Unexpected Gemini response: {resp.text[:300]}")
    return normalise(parse_json(text))


# Tried in order after the configured model if it is overloaded or unavailable.
FALLBACK_MODELS = ["gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-flash-latest"]
RETRYABLE = {429, 500, 503, 504, 599}
TOTAL_BUDGET_SECONDS = 60  # Give up after this long overall, so the page never hangs.


class _NetworkError:
    """Stands in for a response when the request itself failed (timeout, connection)."""
    status_code = 599

    def __init__(self, exc):
        self.text = f"Network problem reaching Gemini: {type(exc).__name__}"


def call_gemini(api_key, model, body, attempts_per_model=2, wait_seconds=1.5):
    """POST to Gemini, retrying busy models and falling back to other models.

    503 'high demand' errors are common and temporary, so a brief retry and then a
    different model usually succeeds. 404 means the model name is not available.
    """
    models = list(dict.fromkeys([model] + FALLBACK_MODELS))  # de-duplicate, keep order
    last = None
    deadline = time.monotonic() + TOTAL_BUDGET_SECONDS
    for m in models:
        for attempt in range(attempts_per_model):
            if time.monotonic() > deadline:
                raise RuntimeError("Gemini is very busy right now and did not answer in time. Try again in a minute.")
            try:
                last = requests.post(
                    GEMINI_URL.format(model=m),
                    json=body,
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    timeout=25,
                )
            except requests.RequestException as e:
                # Timeouts and dropped connections are common under load: treat as busy.
                last = _NetworkError(e)
            if last.status_code == 200:
                return last
            if last.status_code not in RETRYABLE:
                break  # e.g. 404 unknown model: try the next model straight away
            if attempt < attempts_per_model - 1:
                time.sleep(wait_seconds * (attempt + 1))
        if last.status_code in (400, 401, 403):
            break  # Key or request problem: other models will fail the same way.
    raise RuntimeError(f"Gemini error {last.status_code}: {last.text[:300]}")


def parse_json(text):
    """Parse model output, tolerating ```json fences."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(cleaned)


def _strings(value):
    """Turn whatever the model gave (list, string, None, numbers) into clean strings."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if isinstance(v, (str, int, float)) and str(v).strip()]


def _number(value, kind=float):
    try:
        return kind(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _matches(value, pattern):
    return value if isinstance(value, str) and re.fullmatch(pattern, value.strip()) else None


def normalise(prefs):
    """Clean the model output so the rest of the code can trust its shape."""
    if isinstance(prefs, list):  # Some models wrap the object in a list.
        prefs = prefs[0] if prefs and isinstance(prefs[0], dict) else {}
    if not isinstance(prefs, dict):
        prefs = {}
    people = []
    for i, p in enumerate(prefs.get("people") or []):
        if not isinstance(p, dict):
            continue
        people.append({
            "label": str(p.get("label") or f"Person {i + 1}"),
            "likes": sorted({c.lower() for c in _strings(p.get("likes"))}),
            "dislikes": sorted({c.lower() for c in _strings(p.get("dislikes"))}),
            "needs": _strings(p.get("needs")),
        })
    party = _number(prefs.get("party_size"), int)
    if not party or party < 1:
        party = len(people) or None
    time_str = _matches(prefs.get("time"), r"\d{1,2}:\d{2}")
    if time_str and len(time_str) == 4:
        time_str = "0" + time_str  # 7:30 -> 07:30
    return {
        "party_size": party,
        "date": _matches(prefs.get("date"), r"\d{4}-\d{2}-\d{2}"),
        "time": time_str,
        "flex_minutes": _number(prefs.get("flex_minutes"), int),
        "people": people,
        "max_price_level": _number(prefs.get("max_price_level"), int),
        "min_rating": _number(prefs.get("min_rating")),
        "summary": str(prefs.get("summary") or ""),
    }


def cuisine_tally(people):
    """For each cuisine: who likes it, who vetoed it."""
    tally = {}
    for p in people:
        for c in p["likes"]:
            tally.setdefault(c, {"likes": [], "dislikes": []})["likes"].append(p["label"])
        for c in p["dislikes"]:
            tally.setdefault(c, {"likes": [], "dislikes": []})["dislikes"].append(p["label"])
    return tally


def candidate_cuisines(people, limit=MAX_CUISINES):
    """Cuisines nobody vetoed, most popular first. Empty list means 'anything'."""
    tally = cuisine_tally(people)
    ok = [(c, len(v["likes"])) for c, v in tally.items() if v["likes"] and not v["dislikes"]]
    ok.sort(key=lambda x: (-x[1], x[0]))
    return [c for c, _ in ok[:limit]]


def group_fit(cuisine, people):
    """Share of the group who said they like this cuisine (0 to 1)."""
    if not people or not cuisine:
        return 0.5  # No information: neutral.
    likes = sum(1 for p in people if cuisine in p["likes"])
    return likes / len(people)


def rating_norm(restaurant):
    """Map the review-weighted rating from 3.5-5.0 onto 0-1."""
    return max(0.0, min(1.0, (rating_score(restaurant) - 3.5) / 1.5))


def price_ok(restaurant, max_level):
    if not max_level:
        return True
    level = PRICE_LEVELS.get(restaurant.get("price_level"))
    return level is None or level <= int(max_level)  # Unknown price is kept.


def explain(restaurant, cuisine, people):
    parts = []
    if cuisine and people:
        likers = [p["label"] for p in people if cuisine in p["likes"]]
        parts.append(f"{cuisine.title()}: wanted by {len(likers)} of {len(people)} ({', '.join(likers)})")
    rating = restaurant.get("rating")
    if rating is not None:
        parts.append(f"{rating}★ from {restaurant.get('rating_count', 0)} reviews")
    level = PRICE_LEVELS.get(restaurant.get("price_level"))
    if level:
        parts.append("£" * level)
    return " · ".join(parts)


def rank_for_group(places_key, prefs, when, area, min_rating, max_results=5):
    """Search each acceptable cuisine, score by group fit + rating, return the best."""
    people = prefs["people"]
    cuisines = candidate_cuisines(people) or [""]
    seen = {}
    for cuisine in cuisines:
        for r in search_restaurants(places_key, cuisine, area, min_rating, when, max_results=8):
            if not price_ok(r, prefs.get("max_price_level")):
                continue
            fit = group_fit(cuisine, people)
            total = FIT_WEIGHT * fit + RATING_WEIGHT * rating_norm(r)
            if r["id"] not in seen or total > seen[r["id"]]["group_score"]:
                seen[r["id"]] = {
                    **r,
                    "cuisine": cuisine,
                    "group_fit": round(fit, 2),
                    "group_score": round(total, 3),
                    "reason": explain(r, cuisine, people),
                }
    ranked = sorted(seen.values(), key=lambda r: r["group_score"], reverse=True)
    return ranked[:max_results]


def vetoed(people):
    tally = cuisine_tally(people)
    return {c: v["dislikes"] for c, v in tally.items() if v["dislikes"]}


def needs_note(people):
    """Dietary or access needs, phrased for the restaurant call."""
    needs = []
    for p in people:
        for n in p["needs"]:
            if n.lower() not in (x.lower() for x in needs):
                needs.append(n)
    return ", ".join(needs)
