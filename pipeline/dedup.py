"""
Detects when the same sender reposts a near-identical listing (a very
common WhatsApp habit -- brokers repost to stay visible in a busy group).

Two things happen here, in two different places in the pipeline:

  1. deduplicate_message_groups() runs BEFORE chunking/extraction -- this
     is what actually saves money, since a detected repost's raw text
     never gets sent to the API at all. Only the first occurrence does.

  2. attach_repost_info() runs AFTER extraction -- it tries to match each
     extracted listing row back to a repost cluster (by sender + fuzzy
     text similarity against the row's own notes field) and, if it finds
     a confident match, adds how many times it was posted and updates
     the date to the most recent posting.

Honest limitation: step 2 is best-effort, not guaranteed. A single chunk
sent to the API can contain several messages and come back as several
listing rows with no exact 1:1 mapping preserved by the model -- so a row
that doesn't match confidently back to a cluster just keeps its own
extracted date and gets times_posted = 1 (meaning "no repost detected"),
rather than guessing.
"""
from datetime import datetime
from difflib import SequenceMatcher

SIMILARITY_THRESHOLD = 0.87   # how similar two raw messages must be to count as the same repost
NOTES_MATCH_THRESHOLD = 0.55  # looser, since notes are a model's paraphrase, not the raw text


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def deduplicate_message_groups(grouped: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Takes the parsed message groups (chronological, each with sender/text/dt)
    and returns:
      - deduped_groups: only first-occurrence groups -- THIS is what should
        actually get chunked and sent to the API, not the original full list
      - clusters: one entry per deduped group, tracking how many times it
        was reposted and the date of its most recent posting
    """
    clusters = []  # each: {"sender", "text", "times_posted", "first_date", "latest_date"}
    deduped_groups = []

    for group in grouped:
        sender = group.get("sender", "")
        text = group.get("text", "")
        dt = group.get("dt")

        matched_cluster = None
        for cluster in clusters:
            if cluster["sender"] == sender and _similar(cluster["text"], text) >= SIMILARITY_THRESHOLD:
                matched_cluster = cluster
                break

        if matched_cluster:
            matched_cluster["times_posted"] += 1
            if dt and (matched_cluster["latest_date"] is None or dt > matched_cluster["latest_date"]):
                matched_cluster["latest_date"] = dt
            # This repost's raw text is intentionally NOT added to
            # deduped_groups -- it never gets sent to the API.
        else:
            clusters.append({
                "sender": sender,
                "text": text,
                "times_posted": 1,
                "first_date": dt,
                "latest_date": dt,
            })
            deduped_groups.append(group)

    return deduped_groups, clusters


def attach_repost_info(rows: list[dict], clusters: list[dict]) -> list[dict]:
    """
    Best-effort: for each extracted row, tries to find the cluster it came
    from (matching sender + fuzzy-similarity against the row's notes field
    against the cluster's original raw text). If found confidently, adds
    times_posted and updates date to the latest posting. If not, leaves
    the row untouched with times_posted = 1 (meaning "not detected as a
    repost" -- not a claim that it definitely wasn't one).
    """
    for row in rows:
        row.setdefault("times_posted", 1)

        poster = (row.get("poster") or "").strip()
        notes = (row.get("notes") or "") + " " + (row.get("location") or "")
        if not poster or not notes.strip():
            continue

        best_match = None
        best_score = 0.0
        for cluster in clusters:
            if cluster["sender"] != poster or cluster["times_posted"] <= 1:
                continue  # only clusters that actually had a repost are worth attaching
            score = _similar(cluster["text"], notes)
            if score > best_score:
                best_score = score
                best_match = cluster

        if best_match and best_score >= NOTES_MATCH_THRESHOLD:
            row["times_posted"] = best_match["times_posted"]
            if best_match["latest_date"]:
                row["date"] = best_match["latest_date"].strftime("%Y-%m-%d") \
                    if isinstance(best_match["latest_date"], datetime) else str(best_match["latest_date"])

    return rows
