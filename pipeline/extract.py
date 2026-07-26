"""
Sends each chunk of grouped WhatsApp messages to Claude Haiku and gets back
structured listing rows. This is the one paid step in the whole pipeline --
everything else in this project is free, local compute.

Requires: pip install anthropic
Requires: ANTHROPIC_API_KEY environment variable set to your own API key.
"""
import os
import json
import anthropic

MODEL = "claude-haiku-4-5-20251001"

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
- Output ONLY a JSON array of objects. No prose, no markdown fences.
"""


def extract_chunk(chunk_text: str, client: anthropic.Anthropic | None = None) -> list[dict]:
    """Extracts structured listings from one chunk of grouped chat text."""
    client = client or anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": chunk_text}],
    )

    raw = response.content[0].text.strip()
    # Defensive cleanup in case the model wraps output in a code fence anyway
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        # One retry with an explicit correction nudge -- cheap insurance
        # against an occasional malformed response.
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": chunk_text},
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "That wasn't valid JSON. Return ONLY the JSON array, nothing else."},
            ],
        )
        rows = json.loads(response.content[0].text.strip())

    return rows


def extract_all(chunks: list[str]) -> list[dict]:
    """Runs extraction across every chunk and flattens the results."""
    client = anthropic.Anthropic()
    all_rows = []
    for i, chunk in enumerate(chunks, 1):
        try:
            rows = extract_chunk(chunk, client)
            all_rows.extend(rows)
        except Exception as e:
            print(f"[warn] chunk {i}/{len(chunks)} failed: {e}")
    return all_rows
