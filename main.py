#!/usr/bin/env python3
"""
skill_updater — Auto-patch your skill files from Discord messages.

Usage
─────
  python main.py                          # last 7 days (default)
  python main.py --days 14
  python main.py --from 2025-03-01 --to 2025-03-15
  python main.py --days 7 --dry-run      # preview edits, don't write

Environment variables (or .env file)
─────────────────────────────────────
  DISCORD_BOT_TOKEN      required
  DISCORD_CHANNEL_ID     required
  MY_DISCORD_USER_ID     required
  SKILLS_DIR             path to your skills folder  (default: ./skills)
  OLLAMA_MODEL           generation model            (default: llama3)
  EMBEDDING_MODEL        embedding model             (default: same as OLLAMA_MODEL)
  RELEVANCE_THRESHOLD    cosine similarity cutoff    (default: 0.30)
  LOG_FILE               where to append run logs    (default: skill_updater.log)
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
import discord_fetcher as discord_mod
import ollama_client as ollama
import prompt_builder
import skill_patcher as patcher


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(
        description="Auto-patch skill files from Discord messages.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--days", type=int, default=7, metavar="N",
        help="Analyse messages from the last N days (default: 7)"
    )
    g.add_argument(
        "--from", dest="from_date", metavar="YYYY-MM-DD",
        help="Start of custom date range"
    )
    p.add_argument(
        "--to", dest="to_date", metavar="YYYY-MM-DD",
        help="End of custom date range (default: now)"
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print proposed edits as JSON without modifying any files"
    )
    return p.parse_args()


def _resolve_range(args) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if args.from_date:
        start = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end   = (
            datetime.strptime(args.to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if args.to_date else now
        )
    else:
        end   = now
        start = end - timedelta(days=args.days)
    return start, end


def _extract_json(raw: str) -> dict:
    """
    Strip optional markdown fences and parse the JSON the model returned.
    Raises json.JSONDecodeError if the response isn't valid JSON.
    """
    # Remove ```json ... ``` or ``` ... ``` wrappers if the model added them
    clean = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    clean = re.sub(r"\s*```\s*$",        "", clean.strip(), flags=re.MULTILINE)

    try:
        return json.loads(clean.strip())
    except json.JSONDecodeError:
        # Models sometimes include literal newlines/tabs in multi-line content fields
        # or emit Windows path separators without escaping. Attempt both repairs.
        
        # Repair 1: Escape literal newlines and tabs inside quoted strings
        def _escape_control_chars(match: re.Match) -> str:
            prefix = match.group(1)
            value = match.group(2)
            # Escape actual newlines and tabs
            value = value.replace("\n", "\\n")
            value = value.replace("\r", "\\r")
            value = value.replace("\t", "\\t")
            suffix = match.group(3)
            return f"{prefix}{value}{suffix}"

        repaired = re.sub(
            r'("(?:file|content|header|find|replace|summary|action)"\s*:\s*")([^"]*)(")' ,
            _escape_control_chars,
            clean.strip(),
        )
        
        # Repair 2: Escape Windows backslashes in "file" values
        def _escape_file_value(match: re.Match) -> str:
            prefix = match.group(1)
            value = match.group(2)
            # Only escape backslashes that aren't already part of escape sequences
            value = re.sub(r'\\(?![nrt"\\])', r'\\\\', value)
            suffix = match.group(3)
            return f"{prefix}{value}{suffix}"

        repaired = re.sub(
            r'("file"\s*:\s*")([^"]*)(")' ,
            _escape_file_value,
            repaired,
        )
        return json.loads(repaired)


def _log(msg: str):
    """Append a line to the log file and echo to stdout."""
    print(msg)
    try:
        with open(config.LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass  # logging failure must never crash the tool


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    config.validate()
    args  = _parse_args()
    start, end = _resolve_range(args)

    _log(f"\n{'═'*60}")
    _log(f"skill_updater  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    _log(f"Period : {start.date()} → {end.date()}")
    _log(f"Model  : {config.OLLAMA_MODEL}  |  Embed: {config.EMBEDDING_MODEL}")
    _log(f"Skills : {config.SKILLS_DIR}")
    _log(f"{'─'*60}")

    # ── Step 1: Fetch Discord messages ────────────────────────────────────
    messages = discord_mod.fetch_messages(start, end)
    if not messages:
        print("\n[INFO] No messages found in the given period.")
        print("       Hints:")
        print("         • Try a wider window:  --days 30")
        print("         • Check MY_DISCORD_USER_ID is your correct user ID")
        print("         • Confirm the bot is in the right channel")
        sys.exit(0)
    _log(f"[Step 1] {len(messages)} message(s) fetched after noise filtering")

    # ── Step 2: Load skill files ──────────────────────────────────────────
    all_files = patcher.load_skills_folder()
    if not all_files:
        print("\n[ERROR] No skill files loaded.")
        print(f"        SKILLS_DIR is set to: '{config.SKILLS_DIR}'")
        print("        Create or point it at your skills folder.")
        sys.exit(1)
    _log(f"[Step 2] {len(all_files)} file(s) loaded from skills folder")

    # ── Step 3: Relevance filter via embeddings ───────────────────────────
    _log("[Step 3] Running embedding-based relevance filter...")
    relevant_files = patcher.find_relevant_files(messages, all_files)
    _log(f"         {len(relevant_files)}/{len(all_files)} file(s) passed relevance threshold")

    # ── Step 4: Build prompt and call Ollama ──────────────────────────────
    _log("[Step 4] Building prompt...")
    prompt = prompt_builder.build(relevant_files, messages, start, end)
    _log(f"         Prompt length: {len(prompt):,} chars")

    raw_response = ollama.generate(prompt)
    _log(f"         Response length: {len(raw_response):,} chars")

    # ── Step 5: Parse structured JSON ─────────────────────────────────────
    _log("[Step 5] Parsing JSON response...")
    try:
        result = _extract_json(raw_response)
    except (json.JSONDecodeError, ValueError) as e:
        _log(f"[ERROR] JSON parse failed: {e}")
        Path(config.RAW_LOG_FILE).write_text(raw_response, encoding="utf-8")
        _log(f"        Raw response saved to: {config.RAW_LOG_FILE}")
        _log("        Tip: try a more capable model (e.g. mistral-nemo, qwen2.5:14b)")
        sys.exit(1)

    summary    = result.get("summary", "(no summary)")
    edits      = result.get("edits") or []
    no_changes = result.get("no_changes_needed", False)

    _log(f"\n── Summary ─────────────────────────────────────────────")
    _log(summary)
    _log(f"────────────────────────────────────────────────────────")
    _log(f"Edits proposed : {len(edits)}")
    _log(f"No changes flag: {no_changes}")

    # ── Step 6: Apply edits (or dry-run preview) ──────────────────────────
    if no_changes or not edits:
        _log("\n[INFO] Nothing to patch — skill files are already up to date.")
        sys.exit(0)

    if args.dry_run:
        _log("\n[DRY RUN] Proposed edits (not written):")
        print(json.dumps(edits, indent=2, ensure_ascii=False))
        _log("\nRe-run without --dry-run to apply.")
        sys.exit(0)

    _log(f"\n[Step 6] Applying {len(edits)} edit(s)...")
    applied, failed = patcher.apply_edits(edits)

    _log(f"\n[DONE] {applied} edit(s) applied, {failed} failed/skipped")
    _log(f"       Log: {config.LOG_FILE}")

    if failed:
        _log(f"\n[HINT] {failed} edit(s) could not be applied.")
        _log("       Common reasons:")
        _log("         • 'find' text doesn't match exactly (whitespace, capitalisation)")
        _log("         • File path was wrong")
        _log(f"       Check {config.RAW_LOG_FILE} for the raw LLM output.")
        Path(config.RAW_LOG_FILE).write_text(raw_response, encoding="utf-8")


if __name__ == "__main__":
    main()