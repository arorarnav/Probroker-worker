"""
Parses a raw WhatsApp _chat.txt export into clean, grouped message blocks
ready for LLM extraction. This is pure Python -- zero API cost.
"""
import re
from datetime import datetime, date, timedelta

# Matches both plain-space and narrow-no-break-space time formats seen across
# different phone export locales.
MSG_PATTERN = re.compile(
    r'^\u200e?\[(\d{1,2}/\d{1,2}/\d{2}), '
    r'(\d{1,2}:\d{2}:\d{2}\u202f?[AP]M)\] '
    r'([^:]+): ([\s\S]*?)'
    r'(?=(?:\n\u200e?\[\d{1,2}/\d{1,2}/\d{2}, \d{1,2}:\d{2}:\d{2}\u202f?[AP]M\]|\Z))',
    re.MULTILINE
)

NOISE_SUBSTRINGS = [
    "omitted", "added", "created this group", "changed the", "changed this group",
    "Voice chat", "This message was deleted", "end-to-end encrypted",
    "Missed voice call", "Missed video call", "changed their phone number",
    "left", "removed", "facebook.com", "chat.whatsapp.com",
]

DEVOTIONAL_SUBSTRINGS = [
    "जय माता दी", "jai mata di", "जय श्री राम", "राधे राधे", "सुप्रभात",
    "शुभ प्रभात", "गुड मॉर्निंग", "good morning", "गुड नाईट", "जय हिंद",
    "हर हर महादेव", "जय श्री कृष्णा", "जय बजरंग बली", "happy new year", "नव वर्ष",
]

MIN_MESSAGE_LENGTH = 20        # shorter than this is almost never a real listing
GROUP_WINDOW_SECONDS = 600     # messages from the same sender within 10 min = one post


def _is_noise(msg: str) -> bool:
    m = msg.strip().strip('\u200e').strip()
    if len(m) < MIN_MESSAGE_LENGTH:
        return True
    lower = m.lower()
    for p in NOISE_SUBSTRINGS:
        if p.lower() in lower:
            return True
    for p in DEVOTIONAL_SUBSTRINGS:
        if p.lower() in lower:
            return True
    return False


def _parse_dt(d: str, t: str) -> datetime:
    t = t.replace('\u202f', ' ')
    return datetime.strptime(f"{d} {t}", "%m/%d/%y %I:%M:%S %p")


def parse_and_group(raw_text: str, since: date | None = None) -> list[dict]:
    """
    Returns a list of grouped message blocks:
        {"dt": datetime, "sender": str, "text": str}
    `since`, if given, drops any message dated before it -- this is the
    "only listings within the last N months" control from the product's
    upload form.
    """
    matches = MSG_PATTERN.findall(raw_text)

    substantive = []
    for d, t, sender, msg in matches:
        dt = _parse_dt(d, t)
        if since and dt.date() < since:
            continue
        msg_clean = msg.replace('\r', '').strip().strip('\u200e')
        if _is_noise(msg_clean):
            continue
        substantive.append((dt, sender.strip().strip('\u200e'), msg_clean))

    grouped = []
    cur = None
    for dt, sender, msg in substantive:
        if cur and cur["sender"] == sender and (dt - cur["dt"]).total_seconds() <= GROUP_WINDOW_SECONDS:
            cur["text"] += " || " + msg
            cur["dt"] = dt
        else:
            if cur:
                grouped.append(cur)
            cur = {"dt": dt, "sender": sender, "text": msg}
    if cur:
        grouped.append(cur)

    return grouped


def chunk_for_extraction(grouped: list[dict], max_chars: int = 6000) -> list[str]:
    """
    Bundles grouped blocks into LLM-sized chunks. Each chunk includes the
    date/sender header so the model can populate those fields per listing.
    """
    chunks, current, current_len = [], [], 0
    for block in grouped:
        line = f"[{block['dt'].strftime('%Y-%m-%d')}] {block['sender']}: {block['text']}"
        if current_len + len(line) > max_chars and current:
            chunks.append("\n---\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line)
    if current:
        chunks.append("\n---\n".join(current))
    return chunks
