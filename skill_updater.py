#!/usr/bin/env python3
"""
skill_updater.py — Fetch your Discord messages, pipe to Ollama, get skill update suggestions.

Usage:
  python skill_updater.py --days 7                        # last 7 days
  python skill_updater.py --days 1                        # yesterday only
  python skill_updater.py --from 2025-03-01 --to 2025-03-15   # custom range
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone


def load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()

            if val and val[0] in ('"', "'") and val[-1:] == val[0]:
                val = val[1:-1]
            else:
                if " #" in val:
                    val = val.split(" #", 1)[0].rstrip()
                elif "\t#" in val:
                    val = val.split("\t#", 1)[0].rstrip()

            os.environ.setdefault(key, val)

load_dotenv()

# ─── CONFIG ──────────────────────────────────────────────────────────────────
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "")
MY_USER_ID = os.environ.get("MY_DISCORD_USER_ID", "")      # your personal Discord user ID
SKILL_FILE_PATH = os.environ.get("SKILL_FILE", "skill.md") # path to your current skill file
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3")
OUTPUT_FILE = "skill_suggestions.md"
# ─────────────────────────────────────────────────────────────────────────────


def validate_config():
    missing = []
    for name, val in [
        ("DISCORD_BOT_TOKEN", DISCORD_BOT_TOKEN),
        ("DISCORD_CHANNEL_ID", DISCORD_CHANNEL_ID),
        ("MY_DISCORD_USER_ID", MY_USER_ID),
    ]:
        if not val:
            missing.append(name)
    if missing:
        print(f"[ERROR] Missing env vars: {', '.join(missing)}")
        print("Set them before running:\n  export DISCORD_BOT_TOKEN=...")
        sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch Discord messages and generate skill update suggestions.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--days", type=int, default=7, help="Fetch messages from last N days (default: 7)")
    parser.add_argument("--from", dest="from_date", type=str, help="Start date YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", type=str, help="End date YYYY-MM-DD (default: today)")
    return parser.parse_args()


def resolve_date_range(args):
    now = datetime.now(timezone.utc)
    if args.from_date:
        start = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(args.to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.to_date else now
    else:
        end = now
        start = end - timedelta(days=args.days)
    print(f"[INFO] Fetching messages from {start.strftime('%Y-%m-%d %H:%M')} UTC → {end.strftime('%Y-%m-%d %H:%M')} UTC")
    return start, end


def discord_request(path):
    url = f"https://discord.com/api/v10{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "SkillUpdater/1.0"
    })
    with urllib.request.urlopen(req, timeout=15) as res:
        return json.loads(res.read().decode())


# ─── NOISE FILTER ────────────────────────────────────────────────────────────
# Messages matching these patterns carry no skill-relevant information.
# They'll be silently dropped before sending to Ollama.
NOISE_PHRASES = {
    "ok", "okay", "okk", "okkk", "k", "kk",
    "sure", "yep", "yup", "yeah", "yes", "no",
    "got it", "noted", "ack", "acknowledged",
    "go ahead", "sounds good", "lgtm",
    "thanks", "thank you", "ty", "thx",
    "np", "no problem", "no worries",
    "done", "fixed", "pushed", "merged",
    "hmm", "hm", "oh", "ah", "aha",
    "nice", "cool", "great", "awesome", "good",
    "lol", "haha", "hehe", "xd",
    "ping", "pong", "hello", "hi", "hey",
}

def is_noise(text: str) -> bool:
    """
    Returns True if the message carries no skill-relevant information.
    Logic:
      - Strip punctuation/emoji, lowercase
      - If the whole message (after cleanup) is in NOISE_PHRASES → noise
      - If it's very short (≤ 3 words) AND doesn't contain a URL, code, or
        any word longer than 6 chars (proxy for real content) → noise
    """
    import re
    clean = re.sub(r"[^\w\s]", "", text.lower()).strip()
    words = clean.split()

    if not words:
        return True

    # Exact match against known filler phrases
    if clean in NOISE_PHRASES:
        return True

    # Short message with no signal
    if len(words) <= 3:
        has_url = "http" in text or "www." in text
        has_code = "`" in text or "```" in text
        has_real_word = any(len(w) > 6 for w in words)
        if not (has_url or has_code or has_real_word):
            return True

    return False
# ─────────────────────────────────────────────────────────────────────────────


def fetch_single_message(message_id: str) -> dict | None:
    """Fetch one message by ID (for reply-parent context). Returns None on failure."""
    try:
        msg = discord_request(f"/channels/{DISCORD_CHANNEL_ID}/messages/{message_id}")
        return msg
    except urllib.error.HTTPError:
        return None  # message deleted or inaccessible — skip silently


def fetch_messages(start: datetime, end: datetime):
    """
    Paginates Discord channel messages, filters by author + date range.
    For each of your messages that is a reply, also fetches the parent message
    for context — even if the parent is outside the time window.
    Noisy/filler messages are filtered before returning.
    """
    raw_mine = []       # your messages in window (pre noise-filter)
    before_id = None
    page = 0
    parent_cache = {}   # message_id → message dict, avoids duplicate fetches

    print(f"[INFO] Fetching channel messages (filtering for user {MY_USER_ID})...")

    while True:
        path = f"/channels/{DISCORD_CHANNEL_ID}/messages?limit=100"
        if before_id:
            path += f"&before={before_id}"

        try:
            batch = discord_request(path)
        except urllib.error.HTTPError as e:
            print(f"[ERROR] Discord API {e.code}: {e.reason}")
            if e.code == 403:
                print("       Bot lacks READ_MESSAGE_HISTORY permission in this channel.")
            sys.exit(1)

        if not batch:
            break

        page += 1
        before_id = batch[-1]["id"]

        for msg in batch:
            ts = datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00"))

            if ts < start:
                print(f"[INFO] Reached messages older than window after {page} page(s). Done.")
                # Fall through — still process what's collected
                before_id = None  # signal to stop outer loop
                break

            if msg["author"]["id"] == MY_USER_ID and ts <= end:
                raw_mine.append(msg)

        print(f"  Page {page}: {len(batch)} fetched, {len(raw_mine)} yours so far...")

        if before_id is None or len(batch) < 100:
            break

    # ── Now build final message list with noise filtering + reply context ──
    messages = []
    skipped_noise = 0

    for msg in raw_mine:
        content = msg.get("content", "").strip()
        ts = datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00"))
        ts_str = ts.strftime("%Y-%m-%d %H:%M")

        # Check for reply-parent context BEFORE noise filtering:
        # Even a noisy reply ("ok") might need its parent shown for full picture,
        # but we only keep the pair if YOUR message passes noise filter.
        parent_info = None
        ref = msg.get("message_reference")
        if ref and ref.get("message_id"):
            pid = ref["message_id"]
            if pid not in parent_cache:
                parent_msg = fetch_single_message(pid)
                parent_cache[pid] = parent_msg
            parent_msg = parent_cache[pid]
            if parent_msg:
                parent_author = parent_msg.get("author", {}).get("username", "unknown")
                parent_content = parent_msg.get("content", "").strip()
                parent_ts = datetime.fromisoformat(
                    parent_msg["timestamp"].replace("Z", "+00:00")
                ).strftime("%Y-%m-%d %H:%M")
                parent_info = f"[{parent_ts}] @{parent_author}: {parent_content}"

        # Noise filter on YOUR message
        if is_noise(content):
            skipped_noise += 1
            continue

        entry = {"timestamp": ts_str, "content": content, "reply_to": parent_info}
        messages.append(entry)

    print(f"[INFO] After noise filter: {len(messages)} kept, {skipped_noise} skipped.")
    return messages


def load_skill_file():
    if not os.path.exists(SKILL_FILE_PATH):
        print(f"[WARN] Skill file not found at '{SKILL_FILE_PATH}'. Proceeding without it.")
        return "(no existing skill file provided)"
    with open(SKILL_FILE_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    print(f"[INFO] Loaded skill file: {SKILL_FILE_PATH} ({len(content)} chars)")
    return content


def build_prompt(skill_content: str, messages: list, start: datetime, end: datetime) -> str:
    lines = []
    for m in messages:
        if not m["content"]:
            continue
        if m.get("reply_to"):
            lines.append(f"  ↩ replying to → {m['reply_to']}")
        lines.append(f"[{m['timestamp']}] YOU: {m['content']}")
        lines.append("")

    messages_text = "\n".join(lines).strip()

    return f"""You are a skill documentation assistant for an AI bot that answers questions in a Discord server.

Your job: Analyze the Discord messages below (all written by the same person — a maintainer/contributor) 
and suggest improvements to their existing skill/knowledge file.

---

## EXISTING SKILL FILE

{skill_content}

---

## MESSAGES WRITTEN BY THE USER ({start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')})

{messages_text if messages_text else "(no messages in this period)"}

---

## YOUR TASK

1. Identify new topics, questions, or patterns NOT currently covered in the skill file.
2. Identify outdated or incomplete sections that should be expanded.
3. Suggest SPECIFIC additions or edits — write them as ready-to-paste Markdown blocks.
4. Do NOT rewrite the whole file — only suggest targeted changes.
5. If nothing needs to change, say so clearly.

## OUTPUT FORMAT

### Summary
[2-3 sentences on what the messages reveal about gaps or improvements]

### Suggested Additions
[New sections or bullet points to add, with exact Markdown]

### Suggested Edits
[Existing sections to modify, with before/after blocks]

### No Change Needed
[List any areas that are already well-covered]
"""


def call_ollama(prompt: str) -> str:
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    print(f"[INFO] Sending to Ollama ({OLLAMA_MODEL})... this may take a minute.")
    try:
        with urllib.request.urlopen(req, timeout=300) as res:
            data = json.loads(res.read().decode())
            return data.get("response", "").strip()
    except urllib.error.URLError as e:
        print(f"[ERROR] Cannot reach Ollama at {OLLAMA_URL}: {e.reason}")
        print("       Is Ollama running? Try: ollama serve")
        sys.exit(1)


def save_output(content: str, start: datetime, end: datetime):
    header = f"""# Skill Update Suggestions
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Period: {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}
Model: {OLLAMA_MODEL}
Skill file: {SKILL_FILE_PATH}

---

"""
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(header + content)
    print(f"\n[DONE] Suggestions saved to: {OUTPUT_FILE}")


def main():
    validate_config()
    args = parse_args()
    start, end = resolve_date_range(args)

    messages = fetch_messages(start, end)
    print(f"[INFO] Found {len(messages)} message(s) from you in the given period.")

    if not messages:
        print("[INFO] No messages found. Try expanding the date range (e.g. --days 30).")

    skill_content = load_skill_file()
    prompt = build_prompt(skill_content, messages, start, end)
    suggestions = call_ollama(prompt)
    save_output(suggestions, start, end)

    print("\n── PREVIEW ──────────────────────────────────────────")
    print(suggestions[:800] + ("..." if len(suggestions) > 800 else ""))
    print("─────────────────────────────────────────────────────")
    print(f"\nReview '{OUTPUT_FILE}', cherry-pick changes, then push to your skills repo.")


if __name__ == "__main__":
    main()