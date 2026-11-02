"""TableCall: type a dinner request, an AI voice agent phones restaurants to book it.

Run:  python app.py   then open http://localhost:5000
"""
import json
import os
from datetime import datetime

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

import group
from places import search_restaurants, time_window

load_dotenv()
RETELL_API = "https://api.retellai.com"
RETELL_KEY = os.getenv("RETELL_API_KEY")
AGENT_ID = os.getenv("RETELL_AGENT_ID")
PLACES_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

app = Flask(__name__, static_folder="static")


@app.errorhandler(Exception)
def json_error(e):
    """Always answer the page with JSON, so it can show a readable error."""
    app.logger.exception("Unhandled error")  # Full traceback stays in the terminal.
    code = getattr(e, "code", 500)
    if not isinstance(code, int):
        code = 500
    return jsonify(error=f"{type(e).__name__}: {e}"), code


def spoken_time(dt):
    """19:30 -> '7:30pm', 19:00 -> '7pm'."""
    hour = dt.strftime("%I").lstrip("0")
    suffix = "am" if dt.hour < 12 else "pm"
    return f"{hour}{suffix}" if dt.minute == 0 else f"{hour}:{dt.strftime('%M')}{suffix}"


def spoken_date(dt):
    """2026-11-03 -> 'Tuesday 3 November'."""
    return f"{dt.strftime('%A')} {dt.day} {dt.strftime('%B')}"


def retell_headers():
    return {"Authorization": f"Bearer {RETELL_KEY}", "Content-Type": "application/json"}


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.post("/api/search")
def search():
    if not PLACES_KEY:
        return jsonify(error="GOOGLE_PLACES_API_KEY missing from .env"), 500
    d = request.get_json(force=True)
    try:
        when = datetime.strptime(f"{d['date']} {d['time']}", "%Y-%m-%d %H:%M")
        results = search_restaurants(
            PLACES_KEY,
            cuisine=d.get("cuisine", ""),
            area=d.get("area") or "Oxford, UK",
            min_rating=d.get("min_rating", 4.0),
            when=when,
        )
    except (KeyError, ValueError) as e:
        return jsonify(error=f"Bad request: {e}"), 400
    except RuntimeError as e:
        return jsonify(error=str(e)), 502
    return jsonify(restaurants=results)


@app.post("/api/group")
def group_search():
    """Transcript of a group conversation in, preferences + group-ranked shortlist out."""
    if not GEMINI_KEY:
        return jsonify(error="GEMINI_API_KEY missing from .env"), 500
    if not PLACES_KEY:
        return jsonify(error="GOOGLE_PLACES_API_KEY missing from .env"), 500
    d = request.get_json(force=True)
    area = d.get("area") or "Oxford, UK"
    try:
        prefs = group.extract_preferences(GEMINI_KEY, GEMINI_MODEL, d.get("transcript", ""), area=area)
    except json.JSONDecodeError:
        return jsonify(error="Gemini did not return valid JSON. Try again."), 502
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except RuntimeError as e:
        return jsonify(error=str(e)), 502

    # The conversation wins; the form fills any gaps.
    booking_date = prefs["date"] or d.get("date")
    booking_time = prefs["time"] or d.get("time") or "19:30"
    min_rating = prefs["min_rating"] or d.get("min_rating") or 4.0
    try:
        when = datetime.strptime(f"{booking_date} {booking_time}", "%Y-%m-%d %H:%M")
        restaurants = group.rank_for_group(PLACES_KEY, prefs, when, area, min_rating)
    except ValueError as e:
        return jsonify(error=f"Could not read date or time: {e}", preferences=prefs), 400
    except RuntimeError as e:
        return jsonify(error=str(e), preferences=prefs), 502

    return jsonify(
        preferences=prefs,
        vetoed=group.vetoed(prefs["people"]),
        form={
            "date": booking_date,
            "time": booking_time,
            "party_size": prefs["party_size"] or d.get("party_size"),
            "flex_minutes": prefs["flex_minutes"],
            "cuisine": ", ".join(group.candidate_cuisines(prefs["people"])),
            "min_rating": min_rating,
            "notes": group.needs_note(prefs["people"]),
        },
        restaurants=restaurants,
    )


@app.post("/api/call")
def start_call():
    """Create a Retell web call for one restaurant. The browser joins it with the access token."""
    if not (RETELL_KEY and AGENT_ID):
        return jsonify(error="RETELL_API_KEY or RETELL_AGENT_ID missing from .env"), 500
    d = request.get_json(force=True)
    try:
        when = datetime.strptime(f"{d['date']} {d['time']}", "%Y-%m-%d %H:%M")
        earliest, latest = time_window(when, d.get("flex_minutes", 30))
        variables = {
            "restaurant_name": d["restaurant_name"],
            "customer_name": d["customer_name"],
            "party_size": str(int(d["party_size"])),
            "date_spoken": spoken_date(when),
            "preferred_time": spoken_time(when),
            "earliest_time": spoken_time(earliest),
            "latest_time": spoken_time(latest),
            "customer_phone": d.get("customer_phone") or "not available",
            "notes": d.get("notes") or "none",
        }
    except (KeyError, ValueError) as e:
        return jsonify(error=f"Bad request: {e}"), 400

    body = {
        "agent_id": AGENT_ID,
        "retell_llm_dynamic_variables": variables,
        "metadata": {"restaurant_id": d.get("restaurant_id", "")},
    }
    r = requests.post(f"{RETELL_API}/v3/create-web-call", json=body, headers=retell_headers(), timeout=20)
    if r.status_code >= 300:
        return jsonify(error=f"Retell error {r.status_code}: {r.text[:300]}"), 502
    call = r.json()
    return jsonify(
        call_id=call.get("call_id"),
        access_token=call.get("access_token"),
        transport=call.get("transport"),
        ice_servers=call.get("ice_servers"),
    )


@app.get("/api/call/<call_id>")
def get_call(call_id):
    """Fetch the call result. Post-call analysis arrives a few seconds after the call ends."""
    r = requests.get(f"{RETELL_API}/v2/get-call/{call_id}", headers=retell_headers(), timeout=20)
    if r.status_code >= 300:
        return jsonify(error=f"Retell error {r.status_code}: {r.text[:300]}"), 502
    call = r.json()
    analysis = call.get("call_analysis") or {}
    return jsonify(
        status=call.get("call_status"),
        analysed=bool(analysis.get("custom_analysis_data")),
        result=analysis.get("custom_analysis_data") or {},
        summary=analysis.get("call_summary"),
        transcript=call.get("transcript"),
    )


if __name__ == "__main__":
    app.run(port=int(os.getenv("PORT", 5000)), debug=True)
