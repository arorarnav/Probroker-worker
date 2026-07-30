"""
Sends each chunk of grouped WhatsApp messages directly to Claude and gets
back structured listing rows. Calls Anthropic's API directly -- no
OpenRouter markup on top of the model's own price.

Requires: pip install anthropic
Requires: ANTHROPIC_API_KEY environment variable (from console.anthropic.com)
"""
import os
import json
import time
import anthropic

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# A small pause between requests is good practice regardless of provider --
# keeps you well clear of any rate limit rather than bursting requests.
REQUEST_DELAY_SECONDS = float(os.environ.get("ANTHROPIC_REQUEST_DELAY", "0.3"))
MAX_RETRIES_ON_RATE_LIMIT = 3

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

IMPORTANT: Translate every text field — location, size, price, and notes — fully \
into English. Do not leave any Devanagari script anywhere in the output, including \
in notes. Transliterate place names into standard English spelling and translate \
all descriptive text completely, even informal Hinglish phrases. Keep numbers, \
units, and phone numbers as-is.

Rules:
- One listing per distinct property/requirement mentioned, even if several appear \
in one message block.
- Ignore pure chit-chat, forwards, greetings, or anything with no property content.
- Never invent a field that isn't stated -- use null.
- Output ONLY a JSON array of objects. No prose, no markdown fences, no explanation.
"""


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env automatically


def _clean_json_text(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return raw


def extract_chunk(chunk_text: str, client: anthropic.Anthropic | None = None) -> list[dict]:
    """Extracts structured listings from one chunk of grouped chat text."""
    client = client or _get_client()

    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": chunk_text}],
    )
    raw = response.content[0].text

    try:
        return json.loads(_clean_json_text(raw))
    except json.JSONDecodeError:
        # One retry with an explicit correction nudge -- cheap insurance
        # against an occasional malformed response.
        response = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": chunk_text},
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "That wasn't valid JSON. Return ONLY the JSON array, nothing else."},
            ],
        )
        return json.loads(_clean_json_text(response.content[0].text))


def extract_all(chunks: list[str]) -> list[dict]:
    """Runs extraction across every chunk and flattens the results."""
    client = _get_client()
    all_rows = []
    for i, chunk in enumerate(chunks, 1):
        for attempt in range(1, MAX_RETRIES_ON_RATE_LIMIT + 1):
            try:
                rows = extract_chunk(chunk, client)
                all_rows.extend(rows)
                break
            except anthropic.RateLimitError as e:
                if attempt < MAX_RETRIES_ON_RATE_LIMIT:
                    wait = REQUEST_DELAY_SECONDS * attempt * 5
                    print(f"[warn] chunk {i}/{len(chunks)} rate-limited, retrying in {wait:.0f}s (attempt {attempt})...")
                    time.sleep(wait)
                    continue
                print(f"[warn] chunk {i}/{len(chunks)} failed permanently (rate limit): {e}")
                break
            except Exception as e:
                print(f"[warn] chunk {i}/{len(chunks)} failed: {e}")
                break
        time.sleep(REQUEST_DELAY_SECONDS)
    return all_rows
