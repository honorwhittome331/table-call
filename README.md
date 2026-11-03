# TableCall

**Talk it through as a group, and an AI voice agent phones restaurants to book the table.**

TableCall listens to a group deciding where to eat, works out what everyone wants (cuisines, vetoes, dietary and access needs, time, party size, budget), ranks restaurants anywhere in the world by how well they suit the whole group, then uses a voice agent to phone each one in turn until a table is booked.

Built for the Hiya Voice AI Challenge (Productivity track).

## How it works

1. **Listen**: Chrome's speech recognition transcribes the group conversation live (or paste a transcript).
2. **Understand**: Gemini turns the messy transcript into structured preferences per person, including where they want to eat.
3. **Rank**: Google Places finds restaurants that are open at the requested time; each is scored 60% on group fit (share of people who wanted that cuisine) and 40% on a review-weighted rating. Vetoed cuisines and over-budget places are excluded. Each result shows the reason for its ranking.
4. **Call**: A Retell AI voice agent phones the restaurant, says it is an AI calling on the customer's behalf, negotiates a time within the customer's window, never gives payment details, and asks the restaurant to confirm.
5. **Confirm**: Retell's post-call analysis extracts the outcome (booked or not, time, name, conditions). If there is no booking, move on to the next restaurant.

> **Demo mode:** calls run in the browser and you play the restaurant. No real restaurants are phoned. The restaurant's real number is already retrieved from Google Places; dialling it would use Retell's outbound phone call API with a UK number.

## Requirements

- Python 3.10+
- Google Chrome (for the microphone and speech recognition)
- API keys:
  - **Retell AI**: [dashboard.retellai.com](https://dashboard.retellai.com) → Settings → API Keys (new accounts get free credit)
  - **Google Places API (New)**: Google Cloud Console → enable *Places API (New)* → APIs & Services → Credentials → Create API key
  - **Gemini**: [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (free tier)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then add your three API keys to .env
python setup_agent.py              # creates the voice agent; copy the printed RETELL_AGENT_ID into .env
```

## Run

```bash
PORT=5001 python app.py
```

Open **http://localhost:5001** in Chrome and allow microphone access.

(On macOS, port 5000 is taken by AirPlay Receiver, so use 5001.)

## Where it works

Anywhere Google Places covers. The area comes from, in order: a place mentioned in the conversation ("let's go somewhere in Shoreditch"), the **Area** box (any city or neighbourhood), or **Use my location** (searches within about 3 km). Times are local to the restaurant. The calling agent speaks English.

## Try it

**Group mode**
1. Click **Start listening** and talk as a group (use names, e.g. "I'm Amy and I fancy Thai"), or paste a transcript such as:
   > I'm Amy, let's eat in Soho tomorrow, I've been craving Thai all week. Thai sounds good to me, this is Ben, but please not Indian again. Sam here, I could do Thai I suppose but I'd prefer Italian, and I'm vegan. Seven-ish tomorrow? Just the three of us, nothing too pricey.
2. Click **Work out what we want**. The form fills itself and a group-ranked shortlist appears.

**Calling**
1. Click **Call first restaurant**. Answer as the restaurant: "Hello, [restaurant name]".
2. Try: being fully booked, offering a time outside the window, or asking for a card deposit.
3. If no booking is made, click **Call next**.

## Tests

```bash
python -m pytest -q
```

Covers opening-hours filtering (including past midnight), review-weighted ranking, group fit and vetoes, budget filtering, cleaning malformed model output, and Gemini retry and fallback.

## Project structure

| File | Purpose |
|---|---|
| `app.py` | Flask server: search, group analysis, create web call, fetch call outcome |
| `places.py` | Google Places search, opening-hours filter, review-weighted ranking |
| `group.py` | Gemini preference extraction, retries and fallback, group-fit ranking |
| `agent_config.py` | Voice agent prompt and post-call analysis schema |
| `setup_agent.py` | One-off creation of the Retell LLM and agent |
| `static/index.html` | Listening, form, shortlist, browser call and confirmation |
| `test_places.py`, `test_group.py` | Unit tests |

## Troubleshooting

| Problem | Fix |
|---|---|
| "Access to localhost was denied" | Use port 5001 (see Run) |
| "Gemini is very busy" / 503 | Temporary demand on Google's side; the app retries and falls back automatically. Try again, or set `GEMINI_MODEL` in `.env` |
| "Places API error 403" | Enable *Places API (New)* on the same project as the key, and link billing |
| Call will not start | Check the browser console; allow the microphone; use Chrome |

## Limitations

- Demo calls run in the browser rather than over a real phone line.
- Speech recognition has no speaker labels; people are inferred from names and context.
- Chrome's speech recognition sends audio to Google.
- Group fit counts cuisine support, not how strongly each person feels.
