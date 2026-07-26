"""
Finds demand <-> supply adjacencies: a "wants X" post that's plausibly
satisfied by a "has X" post. Pure Python, zero API cost, and this is the
part of the product that's actually hard to copy -- it only gets good with
volume of chats processed, not volume of customers.
"""
import re
from datetime import date, datetime
from difflib import SequenceMatcher

TODAY = date.today()

# Rough per-unit conversion so "50 lakh/bigha" and "12,000/sq ft" don't get
# compared directly, but a demand and supply both in bigha (or both in sq ft)
# can be size-checked against each other.
SIZE_UNIT_HINTS = ["bigha", "acre", "sq ft", "sqft", "sq yd", "sqyd", "biswa"]


NULL_LOCATION_MARKERS = {"unspecified", "n/a", "na", "none", "not mentioned", "unknown", ""}

# Matches a poster field that's actually a phone number (WhatsApp shows the
# raw number when the sender isn't saved as a contact) rather than a name.
# Accepts optional +91/91 prefix, spaces, dashes -- requires 10+ digits.
_PHONE_LIKE = re.compile(r'^[\+]?[\d][\d\s\-]{8,14}\d$')


def fill_missing_demand_contact(rows: list[dict]) -> list[dict]:
    """
    If a demand listing has no contact number but the sender's own name
    field is actually their raw phone number (not a saved contact name),
    use that as the contact -- since posting a "wanted" message with no
    number usually means "call me, I'm right here in the group."

    Does NOT fill in the poster's actual name as a fake contact -- a name
    isn't a callback number, and displaying one as if it were would be
    misleading rather than helpful.
    """
    for r in rows:
        if r.get("listing_type") == "demand" and not r.get("contact"):
            poster = (r.get("poster") or "").strip()
            if _PHONE_LIKE.match(poster):
                r["contact"] = poster
    return rows


def _location_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    a, b = a.lower().strip(), b.lower().strip()
    if a in NULL_LOCATION_MARKERS or b in NULL_LOCATION_MARKERS:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _first_number(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r'[\d,]+(?:\.\d+)?', text.replace(',', ''))
    return float(m.group()) if m else None


def _unit_of(text: str) -> str | None:
    if not text:
        return None
    low = text.lower()
    for u in SIZE_UNIT_HINTS:
        if u in low:
            return u
    return None


def _size_compatibility(demand_size: str, supply_size: str) -> float:
    """Returns 1.0 if sizes are in the same unit and within +/-30%, 0.5 if
    same unit but out of range, 0.3 if units unknown/unlike (weak signal
    either way), 0.0 only never used -- absence of size data shouldn't kill
    an otherwise-good match."""
    du, su = _unit_of(demand_size), _unit_of(supply_size)
    if du and su and du == su:
        dn, sn = _first_number(demand_size), _first_number(supply_size)
        if dn and sn:
            ratio = min(dn, sn) / max(dn, sn)
            return 1.0 if ratio >= 0.7 else 0.4
    return 0.3


def _recency_score(d: str) -> float:
    """More recent posts score higher; decays over ~90 days."""
    try:
        posted = datetime.strptime(d, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return 0.3
    age_days = (TODAY - posted).days
    if age_days < 0:
        return 0.3
    return max(0.0, 1.0 - age_days / 90)


def find_matches(rows: list[dict], location_threshold: float = 0.35, top_n: int = 200) -> list[dict]:
    """
    Compares every demand row against every supply row and returns ranked
    matches above a minimum location-similarity bar.
    """
    demands = [r for r in rows if r.get("listing_type") == "demand"]
    supplies = [r for r in rows if r.get("listing_type") == "supply"]

    matches = []
    for d in demands:
        for s in supplies:
            if d.get("poster") and d.get("poster") == s.get("poster"):
                continue  # a broker's own demand doesn't need matching to their own supply
            loc_sim = _location_similarity(d.get("location", ""), s.get("location", ""))
            if loc_sim < location_threshold:
                continue
            size_score = _size_compatibility(d.get("size", ""), s.get("size", ""))
            recency = (_recency_score(d.get("date")) + _recency_score(s.get("date"))) / 2

            score = loc_sim * 0.5 + size_score * 0.2 + recency * 0.3
            matches.append({
                "score": round(score, 3),
                "demand": d,
                "supply": s,
                "summary": _summarize(d, s),
            })

    matches.sort(key=lambda m: m["score"], reverse=True)
    return matches[:top_n]


def _summarize(d: dict, s: dict) -> str:
    d_age = (TODAY - datetime.strptime(d["date"], "%Y-%m-%d").date()).days if d.get("date") else "?"
    s_age = (TODAY - datetime.strptime(s["date"], "%Y-%m-%d").date()).days if s.get("date") else "?"
    return (
        f"{d.get('poster', 'Someone')} wants {d.get('size') or 'a property'} in "
        f"{d.get('location', 'unspecified')} (posted {d_age}d ago); "
        f"{s.get('poster', 'Someone')} has a matching listing in "
        f"{s.get('location', 'unspecified')} (posted {s_age}d ago)."
    )
