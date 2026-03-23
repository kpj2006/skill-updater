"""
discord_fetcher.py — Fetch YOUR messages from a Discord channel.

Features:
  - Paginated read (handles thousands of messages efficiently)
  - Filters by author ID + date window
  - Fetches reply-parent messages for context
  - Noise-filters filler/one-word messages before returning
"""
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

import config

# ── Noise filter ──────────────────────────────────────────────────────────────
# Messages whose entire content (after cleanup) matches one of these short filler
# phrases carry zero skill-relevant information.

_NOISE_EXACT = {
    "ok", "okay", "okk", "okkk", "k", "kk",
    "sure", "yep", "yup", "yeah", "yes", "no",
    "got it", "noted", "ack", "acknowledged",
    "go ahead", "sounds good", "lgtm",
    "thanks", "thank you", "ty", "thx",
    "np", "no problem", "no worries",
    "done", "fixed", "pushed", "merged", "shipped",
    "hmm", "hm", "oh", "ah", "aha",
    "nice", "cool", "great", "awesome", "good", "perfect",
    "lol", "haha", "hehe", "xd", "lmao",
    "ping", "pong", "hello", "hi", "hey", "yo",
    "wdym", "nvm", "fyi", "iirc", "afaik", "tbh",
    "brb", "gtg", "omw", "eta", "asap",
}


def is_noise(text: str) -> bool:
    """
    Returns True if the message carries no skill-relevant content.

    Logic (in order):
      1. Empty → noise
      2. Whole message (after stripping punctuation/emoji) matches a known filler phrase → noise
      3. Very short (≤ 3 words) AND no URL, code block, or word longer than 6 chars → noise
      4. Otherwise → keep
    """
    clean = re.sub(r"[^\w\s]", "", text.lower()).strip()
    words = clean.split()

    if not words:
        return True

    # Exact filler phrase
    if clean in _NOISE_EXACT:
        return True

    # Short with no real signal
    if len(words) <= 3:
        has_url      = "http" in text or "www." in text
        has_code     = "`" in text
        has_longword = any(len(w) > 6 for w in words)
        if not (has_url or has_code or has_longword):
            return True

    return False


# ── Discord HTTP ──────────────────────────────────────────────────────────────

def _request(path: str):
    url = f"https://discord.com/api/v10{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bot {config.DISCORD_BOT_TOKEN}",
        "Content-Type":  "application/json",
        "User-Agent":    "SkillUpdater/2.0",
    })
    with urllib.request.urlopen(req, timeout=15) as res:
        return json.loads(res.read())


def _fetch_single_message(message_id: str) -> dict | None:
    """Fetch one message by ID for reply-parent context. Returns None if gone."""
    try:
        return _request(f"/channels/{config.DISCORD_CHANNEL_ID}/messages/{message_id}")
    except urllib.error.HTTPError:
        return None  # deleted or inaccessible — skip silently


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_messages(start: datetime, end: datetime) -> list[dict]:
    """
    Return a list of your messages in the given date window (noise-filtered).

    Each entry:
      {
        "timestamp": "YYYY-MM-DD HH:MM",
        "content":   "<your message>",
        "reply_to":  "<parent message text>" | None,
      }
    """
    print(f"[Discord] Fetching messages for user {config.MY_USER_ID}")
    print(f"          Window: {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}")

    raw_mine: list[dict] = []
    before_id: str | None = None
    page = 0
    parent_cache: dict[str, dict | None] = {}

    # ── Paginate ──────────────────────────────────────────────────────────
    while True:
        path = f"/channels/{config.DISCORD_CHANNEL_ID}/messages?limit=100"
        if before_id:
            path += f"&before={before_id}"

        try:
            batch = _request(path)
        except urllib.error.HTTPError as e:
            print(f"[ERROR] Discord API returned {e.code}: {e.reason}")
            if e.code == 403:
                print("        → Bot is missing READ_MESSAGE_HISTORY permission.")
            elif e.code == 401:
                print("        → DISCORD_BOT_TOKEN is invalid.")
            sys.exit(1)

        if not batch:
            break

        page += 1
        stop = False

        for msg in batch:
            ts = datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00"))
            if ts < start:
                stop = True  # older than our window — no point paginating further
                break
            if msg["author"]["id"] == config.MY_USER_ID and ts <= end:
                raw_mine.append(msg)

        before_id = batch[-1]["id"]
        print(f"  Page {page}: {len(batch)} fetched, {len(raw_mine)} yours so far")

        if stop or len(batch) < 100:
            break

    # ── Build final list: noise filter + reply context ────────────────────
    messages: list[dict] = []
    skipped = 0

    for msg in raw_mine:
        content = msg.get("content", "").strip()

        # Resolve reply parent BEFORE noise-filtering — even a "thanks" might
        # have an important parent message we want to log.
        parent_info: str | None = None
        ref = msg.get("message_reference") or {}
        pid = ref.get("message_id")
        if pid:
            if pid not in parent_cache:
                parent_cache[pid] = _fetch_single_message(pid)
            parent = parent_cache[pid]
            if parent:
                p_ts  = datetime.fromisoformat(
                    parent["timestamp"].replace("Z", "+00:00")
                ).strftime("%Y-%m-%d %H:%M")
                p_author  = parent.get("author", {}).get("username", "?")
                p_content = parent.get("content", "").strip()
                parent_info = f"[{p_ts}] @{p_author}: {p_content}"

        # Now noise-filter YOUR message
        if is_noise(content):
            skipped += 1
            continue

        messages.append({
            "timestamp": datetime.fromisoformat(
                msg["timestamp"].replace("Z", "+00:00")
            ).strftime("%Y-%m-%d %H:%M"),
            "content":  content,
            "reply_to": parent_info,
        })

    print(f"[Discord] Done — {len(messages)} kept, {skipped} noise-filtered")
    return messages