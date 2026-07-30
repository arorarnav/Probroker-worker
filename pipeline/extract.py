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
from pipeline.cost_control import INPUT_PRICE_PER_TOKEN, OUTPUT_PRICE_PER_TOKEN

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


def _real_cost(response) -> float:
    """Computes the ACTUAL cost of one API call from Anthropic's own
    reported token usage -- not an estimate. Accounts for prompt caching:
    a cache write costs MORE than normal input (1.25x), a cache read
    costs far LESS (0.1x) -- using plain input pricing for cached tokens
    would misreport the real cost once caching is active."""
    usage = response.usage
    regular_input = getattr(usage, "input_tokens", 0)
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0

    cost = regular_input * INPUT_PRICE_PER_TOKEN
    cost += cache_write * INPUT_PRICE_PER_TOKEN * 1.25
    cost += cache_read * INPUT_PRICE_PER_TOKEN * 0.1
    cost += usage.output_tokens * OUTPUT_PRICE_PER_TOKEN
    return cost


def _sanitize_rows(rows: list[dict]) -> list[dict]:
    """
    Defensive cleanup: the model is instructed to return a simple string
    (or null) for every field, but occasionally returns a list instead --
    e.g. two phone numbers for one listing, as ['+91...', '+91...']
    instead of one joined string. Excel/openpyxl cannot write a raw list
    into a cell and crashes, so this joins any list into a plain string
    (and stringifies any other unexpected type) before it ever reaches
    the report-building step, no matter what the model returns.
    """
    for row in rows:
        for key, value in list(row.items()):
            if isinstance(value, list):
                row[key] = ", ".join(str(v) for v in value if v is not None)
            elif isinstance(value, dict):
                row[key] = str(value)
    return rows


def extract_chunk(chunk_text: str, client: anthropic.Anthropic | None = None) -> tuple[list[dict], float]:
    """Extracts structured listings from one chunk. Returns (rows, real_cost_usd)
    -- the real cost of every call made for this chunk, including a retry
    if one was needed, since a retry re-sends the full context and genuinely
    costs money too."""
    client = client or _get_client()
    total_cost = 0.0

    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=8192,  # raised from 4096 -- real usage data showed AVERAGE
                          # output per chunk on a dense chat already exceeded
                          # the old ceiling, silently truncating listings
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": chunk_text}],
    )
    total_cost += _real_cost(response)
    raw = response.content[0].text

    try:
        return _sanitize_rows(json.loads(_clean_json_text(raw))), total_cost
    except json.JSONDecodeError:
        # One retry with an explicit correction nudge -- this re-sends the
        # full original context too, so it costs real money, tracked here.
        response = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=8192,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {"role": "user", "content": chunk_text},
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "That wasn't valid JSON. Return ONLY the JSON array, nothing else."},
            ],
        )
        total_cost += _real_cost(response)
        return _sanitize_rows(json.loads(_clean_json_text(response.content[0].text))), total_cost


def extract_all(chunks: list[str], max_cost_usd: float = None) -> tuple[list[dict], float, bool]:
    """
    Runs extraction across chunks, tracking REAL cumulative cost from
    Anthropic's own reported usage after every single call -- not a
    one-time estimate made before any of this ran.

    If max_cost_usd is given, this STOPS immediately (mid-run, not just
    at the start) the instant real spend reaches that cap, regardless of
    how many chunks are left -- this is the actual hard ceiling, enforced
    against reality as it happens, not a guess made in advance.

    Returns (rows, real_total_cost_usd, was_stopped_early).
    """
    client = _get_client()
    all_rows = []
    running_cost = 0.0
    was_stopped_early = False

    for i, chunk in enumerate(chunks, 1):
        if max_cost_usd is not None and running_cost >= max_cost_usd:
            print(f"[budget] real spend (${running_cost:.3f}) hit the ${max_cost_usd:.2f} cap -- "
                  f"stopping here, {len(chunks) - i + 1} chunk(s) not processed")
            was_stopped_early = True
            break

        for attempt in range(1, MAX_RETRIES_ON_RATE_LIMIT + 1):
            try:
                rows, cost = extract_chunk(chunk, client)
                all_rows.extend(rows)
                running_cost += cost
                break
            except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
                # Rate limits AND transient connection/timeout blips both get
                # retried -- a brief network hiccup shouldn't be allowed to
                # fail an otherwise-working report.
                if attempt < MAX_RETRIES_ON_RATE_LIMIT:
                    wait = REQUEST_DELAY_SECONDS * attempt * 5
                    print(f"[warn] chunk {i}/{len(chunks)} {type(e).__name__}, retrying in {wait:.0f}s (attempt {attempt})...")
                    time.sleep(wait)
                    continue
                print(f"[warn] chunk {i}/{len(chunks)} failed permanently ({type(e).__name__}): {e}")
                break
            except Exception as e:
                print(f"[warn] chunk {i}/{len(chunks)} failed: {e}")
                break
        time.sleep(REQUEST_DELAY_SECONDS)

    print(f"  real cost so far: ${running_cost:.3f}")
    return all_rows, running_cost, was_stopped_early

