# AI tools used

## Claude (Anthropic): development assistant
- **Research:** checked Retell's current API (including the move to the v3 web call endpoint), Retell pricing and free-credit limits, Google Places API (New) and the Gemini API.
- **Code generation:** wrote the Flask backend, Places search and ranking, Retell agent setup script, group-listening feature, front-end page and unit tests.
- **Debugging:** diagnosed issues from my error messages and tracebacks and wrote fixes.

## What I did
- Chose the idea and the scope, and decided not to phone real restaurants during development.
- Took up the Hiya team's office-hours suggestion to listen to a group conversation, and chose how it should work (LLM for understanding, deterministic scoring for ranking).
- Set up the Retell, Google Cloud and Gemini accounts and keys; ran and tested the app, including several group conversations and difficult restaurant scenarios.
- Found problems in live testing and directed the fixes:
  - the agent repeated the booking details several times in a call;
  - the final confirmation was a statement, so the "restaurant" didn't realise it needed to answer, so I asked for it to be an explicit question;
  - the macOS port 5000 conflict with AirPlay Receiver;
  - Gemini 503 "high demand" errors and timeouts, which led to automatic retries and model fallback.
- Reviewed the code so I can explain how it works and why each design choice was made.

## AI inside the product
- **Retell AI**: runs the voice agent (speech-to-text, LLM, text-to-speech) and post-call analysis that extracts the booking outcome.
- **Google Gemini**: turns the group conversation transcript into structured preferences.
- **Chrome Web Speech API**: live transcription of the group conversation.
