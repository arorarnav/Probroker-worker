"""
Hard cost ceiling per report, enforced BEFORE any API call is made.

Parsing and chunking a chat costs nothing (pure Python), so we can estimate
the total spend for a report in advance and decide what to actually send to
the API -- rather than finding out the cost after the fact.

If a customer's selected window would cost more than the ceiling to process
fully, we don't reject the report -- we keep the MOST RECENT chunks (which
are also the most business-relevant) and drop the oldest ones, so the
report still comes back useful, just capped.
"""
import os

# Cost cap per pricing tier, in INR -- must correspond to the tiers in
# lib/pricing.js (3/6/12/60 months). Higher tiers get a higher cap since
# they genuinely need to cover more chat history, while still preserving
# a healthy margin against what the customer paid for that tier.
COST_CAP_INR_BY_TIER = {
    3: 50,
    6: 80,
    12: 100,
    60: 150,
}

# Approximate conversion -- update if the rate moves meaningfully; this
# doesn't need to be exact, it's a cost-control ceiling, not a billing figure.
INR_PER_USD = float(os.environ.get("INR_PER_USD", "83"))


def get_cost_cap_usd(months_back: int) -> float:
    """
    Looks up the USD cost cap for a given report's chosen window. Falls
    back to the highest tier's cap for any months_back value that doesn't
    exactly match a known tier -- safer to slightly overspend on an
    unexpected edge case than to silently under-cap a legitimate report.
    """
    cap_inr = COST_CAP_INR_BY_TIER.get(months_back, max(COST_CAP_INR_BY_TIER.values()))
    return cap_inr / INR_PER_USD


# Claude Haiku's published per-token pricing (USD per token, not per million --
# already divided down for direct use in the estimate below).
INPUT_PRICE_PER_TOKEN = 1.00 / 1_000_000
OUTPUT_PRICE_PER_TOKEN = 5.00 / 1_000_000

# Deliberately conservative: Hindi/Hinglish text tokenizes at fewer
# characters-per-token than plain English, so a low estimate here means we
# OVERestimate cost rather than underestimate and blow past the ceiling.
CHARS_PER_TOKEN_ESTIMATE = 2.5

# Based on real measured output size from today's actual runs -- each
# chunk's extracted JSON tends to run in this range regardless of input size.
ESTIMATED_OUTPUT_TOKENS_PER_CHUNK = 400


def estimate_chunk_cost(chunk_text: str) -> float:
    """Estimated USD cost of processing one chunk, before it's ever sent."""
    input_tokens = len(chunk_text) / CHARS_PER_TOKEN_ESTIMATE
    return (input_tokens * INPUT_PRICE_PER_TOKEN) + (ESTIMATED_OUTPUT_TOKENS_PER_CHUNK * OUTPUT_PRICE_PER_TOKEN)


def cap_chunks_to_budget(chunks: list[str], max_cost_usd: float) -> tuple[list[str], bool, float]:
    """
    Chunks arrive in chronological order (oldest first, since that's how
    WhatsApp exports read). This keeps chunks starting from the MOST RECENT
    end, backward, only as long as the running estimated cost stays under
    budget -- so if something has to be dropped, it's always the oldest
    data, never the newest.

    max_cost_usd should come from get_cost_cap_usd(months_back) for that
    specific report -- there's no single flat default anymore, since the
    cap now depends on which pricing tier the customer paid for.

    Returns (chunks_to_actually_process, was_truncated, estimated_cost_usd).
    """
    total_cost = 0.0
    kept_newest_first = []
    for chunk in reversed(chunks):
        cost = estimate_chunk_cost(chunk)
        if total_cost + cost > max_cost_usd:
            break
        total_cost += cost
        kept_newest_first.append(chunk)

    kept = list(reversed(kept_newest_first))  # restore chronological order
    was_truncated = len(kept) < len(chunks)
    return kept, was_truncated, total_cost
