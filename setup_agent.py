"""One-off script: create the Retell LLM and agent, then print the agent ID.

Run once:  python setup_agent.py
Then copy the printed RETELL_AGENT_ID into your .env file.
"""
import os
import sys

import requests
from dotenv import load_dotenv

from agent_config import GENERAL_PROMPT, POST_CALL_ANALYSIS

API = "https://api.retellai.com"


def main():
    load_dotenv()
    key = os.getenv("RETELL_API_KEY")
    if not key:
        sys.exit("RETELL_API_KEY missing from .env")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    llm_body = {
        "model": os.getenv("RETELL_MODEL", "gpt-4.1-mini"),
        "general_prompt": GENERAL_PROMPT,
        # On a real phone call the restaurant answers first, so the user speaks first.
        "start_speaker": "user",
        "begin_after_user_silence_ms": 3000,
        "general_tools": [{
            "type": "end_call",
            "name": "end_call",
            "description": "End the call once the booking is confirmed or declined and goodbyes are said.",
        }],
    }
    r = requests.post(f"{API}/create-retell-llm", json=llm_body, headers=headers, timeout=30)
    if r.status_code >= 300:
        sys.exit(f"Failed to create LLM ({r.status_code}): {r.text}")
    llm_id = r.json()["llm_id"]
    print(f"Created Retell LLM: {llm_id}")

    agent_body = {
        "agent_name": "TableCall booking agent",
        "response_engine": {"type": "retell-llm", "llm_id": llm_id},
        "voice_id": os.getenv("RETELL_VOICE_ID", "11labs-Adrian"),
        "language": "en-GB",
        "post_call_analysis_data": POST_CALL_ANALYSIS,
    }
    r = requests.post(f"{API}/create-agent", json=agent_body, headers=headers, timeout=30)
    if r.status_code >= 300:
        sys.exit(
            f"Failed to create agent ({r.status_code}): {r.text}\n"
            f"The LLM {llm_id} was created; delete it in the dashboard if you retry."
        )
    agent_id = r.json()["agent_id"]
    print("\nAdd this line to your .env file:")
    print(f"RETELL_AGENT_ID={agent_id}")


if __name__ == "__main__":
    main()
