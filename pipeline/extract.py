"""
Sends each chunk of grouped WhatsApp messages to a model via OpenRouter and
gets back structured listing rows.

OpenRouter's API is OpenAI-compatible, so this uses the standard `openai`
Python package, just pointed at OpenRouter's servers instead of OpenAI's.

Requires: pip install openai
Requires: OPENROUTER_API_KEY environment variable (get one free at
          openrouter.ai -- no card needed for free-tier models)

The model itself is set by DEFAULT_MODEL below, or via an OPENROUTER_MODEL
environment variable if you want to swap models without editing code.
Check openrouter.ai/models for the current free-tier list before picking
one -- the free lineup rotates over time.
"""
import os
import json
from openai import OpenAI

# Change this (or set OPENROUTER_MODEL as an env var / GitHub secret) to
# swap models without touching any other code.
DEFAULT_MODEL = "openai/gpt-oss-120b:free"

SYSTEM_PROMPT = """You extract real-estate listings from noisy, informal WhatsApp \
messages (mixed Hindi/Hinglish/English). For each distinct listing you find, output \
one JSON object with these exact fields:

- date: the message date, format YYYY-MM-DD
- poster: sender name as given
- listing_type: one of "supply", "demand", "rental", "other"
- location: locality/area, cleaned up but not invented
- size: area/size as stated (keep original units -- bigha, sq ft, sq yd, etc.)
- price: price/rate as stated, or null if not mentioned
- contact: phone number(s) if given, or null
- notes: any other relevant detail (facing, road width, frontage, restrictions), or null

Rules:
- One listing per distinct property/requirement mentioned, even if several appear \
in one message block.
- Ignore pure chit-chat, forwards, greetings, or anything with no property content.
- Never invent a field that isn't stated -- use null.
- Output ONLY a JSON array of objects. No prose, no markdown fences, no explanation.
"""


def _get_client() -> OpenAI:
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )


def _clean_json_text(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return raw


def extract_chunk(chunk_text: str, client: OpenAI | None = None) -> list[dict]:
    """Extracts structured listings from one chunk of grouped chat text."""
    client = client or _get_client()
    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": chunk_text},
        ],
    )
    raw = response.choices[0].message.content

    try:
        return json.loads(_clean_json_text(raw))
    except json.JSONDecodeError:
        # One retry with an explicit correction nudge -- cheap insurance
        # against an occasional malformed response, same safety net as before.
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": chunk_text},
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "That wasn't valid JSON. Return ONLY the JSON array, nothing else."},
            ],
        )
        return json.loads(_clean_json_text(response.choices[0].message.content))


def extract_all(chunks: list[str]) -> list[dict]:
    """Runs extraction across every chunk and flattens the results."""
    client = _get_client()
    all_rows = []
    for i, chunk in enumerate(chunks, 1):
        try:
            rows = extract_chunk(chunk, client)
            all_rows.extend(rows)
        except Exception as e:
            print(f"[warn] chunk {i}/{len(chunks)} failed: {e}")
    return all_rows
