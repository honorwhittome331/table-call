"""Restaurant search using the Google Places API (New) Text Search.

Finds restaurants matching cuisine, area and minimum rating, keeps only those
open at the requested time, and ranks them.
"""
from datetime import datetime, timedelta

import requests

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.rating",
    "places.userRatingCount",
    "places.internationalPhoneNumber",
    "places.regularOpeningHours",
    "places.priceLevel",
])

MINUTES_PER_WEEK = 7 * 24 * 60
NEARBY_RADIUS_M = 3000.0  # "Near me" search radius.
# How long the table must stay available after arrival for us to call it "open".
MIN_SITTING_MINUTES = 60


def build_query(cuisine, area, location=None):
    """Build a Places Text Search body for anywhere in the world.

    `area` is free text ("Soho, London", "Manhattan, NY"). `location` is an optional
    {"lat": .., "lng": ..} from the browser, used to bias results to nearby places.
    """
    area = (area or "").strip()
    if not area and not location:
        raise ValueError("Please enter an area (e.g. 'Soho, London') or use your location.")
    text = f"{cuisine.strip()} restaurant".strip()
    body = {"textQuery": f"{text} in {area}" if area else text, "includedType": "restaurant"}
    if location and not area:
        body["locationBias"] = {"circle": {
            "center": {"latitude": float(location["lat"]), "longitude": float(location["lng"])},
            "radius": NEARBY_RADIUS_M,
        }}
    return body


def search_restaurants(api_key, cuisine, area, min_rating, when, max_results=5, location=None):
    """Return a ranked list of restaurants open at `when` (local time at the restaurant)."""
    body = build_query(cuisine, area, location)
    body.update({"minRating": float(min_rating), "pageSize": 20})
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    resp = requests.post(PLACES_URL, json=body, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Places API error {resp.status_code}: {resp.text[:300]}")

    places = resp.json().get("places", [])
    results = []
    for p in places:
        hours = p.get("regularOpeningHours")
        if hours is not None and not is_open_for_sitting(hours, when):
            continue  # Unknown hours are kept; the call will find out.
        results.append({
            "id": p.get("id"),
            "name": p.get("displayName", {}).get("text", "Unknown"),
            "address": p.get("formattedAddress", ""),
            "rating": p.get("rating"),
            "rating_count": p.get("userRatingCount", 0),
            "phone": p.get("internationalPhoneNumber"),
            "price_level": p.get("priceLevel"),
            "hours_known": hours is not None,
        })

    results.sort(key=score, reverse=True)
    return results[:max_results]


def score(r):
    """Bayesian-adjusted rating: a 4.8 from 12 reviews ranks below a 4.6 from 900."""
    prior_mean, prior_weight = 4.0, 50
    n = r.get("rating_count") or 0
    rating = r.get("rating") or prior_mean
    return (n * rating + prior_weight * prior_mean) / (n + prior_weight)


def _week_minute(day, hour, minute):
    """Google uses day 0 = Sunday."""
    return (day * 24 * 60 + hour * 60 + minute) % MINUTES_PER_WEEK


def is_open_for_sitting(opening_hours, when, sitting=MIN_SITTING_MINUTES):
    """True if the place is open at `when` and stays open for `sitting` minutes."""
    periods = opening_hours.get("periods") or []
    if not periods:
        return True  # No structured data; do not exclude.

    google_day = (when.weekday() + 1) % 7  # Python Monday=0 -> Google Sunday=0
    start = _week_minute(google_day, when.hour, when.minute)
    end = (start + sitting) % MINUTES_PER_WEEK

    for period in periods:
        o = period.get("open")
        c = period.get("close")
        if o is None:
            continue
        if c is None:
            return True  # Open 24 hours.
        o_min = _week_minute(o.get("day", 0), o.get("hour", 0), o.get("minute", 0))
        c_min = _week_minute(c.get("day", 0), c.get("hour", 0), c.get("minute", 0))
        if _within(o_min, c_min, start) and _within(o_min, c_min, end):
            return True
    return False


def _within(open_min, close_min, t):
    """Is week-minute t inside [open, close], handling wrap past Saturday night."""
    if open_min <= close_min:
        return open_min <= t <= close_min
    return t >= open_min or t <= close_min


def time_window(preferred, flex_minutes):
    """Return (earliest, latest) datetimes around the preferred time."""
    delta = timedelta(minutes=int(flex_minutes))
    return preferred - delta, preferred + delta
