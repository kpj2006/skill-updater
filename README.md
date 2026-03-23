# skill_updater v2

**Automatically document your team's knowledge from Discord conversations.**

Analyses your Discord messages, uses AI embeddings to score which skill files are relevant,
then generates and **directly applies structured edits** to update your skill documentation.
No manual copy-paste. No separate suggestions files. No confirmation prompts needed.

## What it does

```
Your Discord messages (8 messages found)
      ↓
      ├─ Noise filter        (remove "ok", "thanks", etc)
      ├─ Embedding scorer    (which files are relevant?)
      ├─ LLM generation      (what edits should be made?)
      └─ Auto-patcher        (apply edits in-place)

Result: skill.md, references/*.md, scripts/* are updated automatically
```

## Key Features

✅ **Learns from your team** — Watches Discord, extracts knowledge
✅ **Smart filtering** — Ignores noise, focuses on substance
✅ **Selective patching** — Only updates relevant files (saves tokens, faster)
✅ **Direct updates** — Changes go straight to disk, ready to git diff/commit
✅ **Safe by default** — Logs all changes, never corrupts files
✅ **Easy audit trail** — All ops logged, rollback with git checkout


```bash
python main.py --days 7

```

**What you'll see:**
- `[Step 1]` — 8+ messages fetched from Discord
- `[Step 2]` — 5 skill files loaded
- `[Step 3]` — 3 files scored as relevant
- `[Step 4]` — ~XX edits generated
- `[Step 5]` — 3 edits applied successfully
- Then: open `.skills/skill.md` — new sections auto-added

### Example Discord Messages for Better Demo Results

Post these to see impressive auto-documentation:

```
1. How do we handle async/await patterns? I notice inconsistent error handling — should we standardize on try-catch or .catch() chains?

2. Documentation gap: we need a PR validation checklist. Must include: test coverage >80%, no console.log, JSDoc on all functions.

3. Security issue: no rate limiting on login endpoint. Should enforce max 5 attempts per minute per IP.

4. Performance: cache user sessions for 5 minutes instead of hitting DB every request. Could reduce load by 30%.
```

---

## File structure

```
skill_updater/
├── main.py              # CLI entry point — run this
├── config.py            # All env vars & constants
├── discord_fetcher.py   # Discord API pagination + noise filter
├── ollama_client.py     # generate() + embed() + cosine()
├── skill_patcher.py     # Load files, relevance scoring, apply edits
└── prompt_builder.py    # Builds the structured JSON prompt
```

---

## Prerequisites

- **Python 3.10+** (uses `X | Y` type hints)
- **Discord bot** with Read Message History permission in target channel

---

## Setup

### 1. Create `.env`

```bash
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_CHANNEL_ID=123456789012345678    # right-click channel → Copy Channel ID
MY_DISCORD_USER_ID=987654321098765432   # Settings → Advanced → Developer Mode → right-click yourself

SKILLS_DIR=./.skills                     # folder containing skill.md etc.
OLLAMA_MODEL=qwen2.5:7b                  # generation model
EMBEDDING_MODEL=nomic-embed-text         # embedding model (lighter = faster)
RELEVANCE_THRESHOLD=0.30                 # 0.0–1.0, lower = more files included
```

**How to get your User ID:**
Discord → Settings → Advanced → enable Developer Mode → right-click your name anywhere → Copy User ID

**How to get Channel ID:**
Right-click the channel name → Copy Channel ID

### 2. Install Ollama models

```bash
ollama pull qwen2.5:7b          # or mistral-nemo, hermes3, etc.
ollama pull nomic-embed-text    # lightweight embedding model
```

---

## Usage

```bash
# Activate your env / install nothing — stdlib only
python main.py                             # last 7 days
python main.py --days 14                   # last 2 weeks
python main.py --from 2025-03-01 --to 2025-03-15
python main.py --days 7 --dry-run          # preview JSON, write nothing
```

---

## How edits work

The LLM returns a JSON array of edit operations.  `skill_patcher.apply_edits()`
handles four action types:

| action           | what it does                                        |
|------------------|-----------------------------------------------------|
| `append_section` | Adds a `## Header` + body at the end of a file      |
| `replace`        | Replaces first occurrence of an exact string        |
| `append_end`     | Appends raw content at the very bottom of a file    |
| `create`         | Creates a new reference file under `skills/`        |

If a `replace` operation's `find` text isn't found verbatim in the file,
it is skipped and logged — it never silently corrupts content.

---

## Relevance filtering

Before building the prompt, each file in your skills folder is scored against
your Discord messages using cosine similarity on Ollama embeddings.

- `skill.md` (or your primary skill file) is **always** included.
- Other files are included only if their similarity score ≥ `RELEVANCE_THRESHOLD`.
- If embeddings fail (e.g. model not pulled), all files are included as a fallback.

This keeps prompts short even when your skills folder grows large.

---

## Automation

### Linux/macOS (cron)

```bash
crontab -e
# Every Monday at 9 AM
0 9 * * 1 cd /path/to/skill_updater && source .env && python main.py --days 7 >> skill_updater.log 2>&1
```

### Windows (Task Scheduler)

Create `run.bat`:
```bat
@echo off
cd /d "C:\path\to\skill_updater"
set DISCORD_BOT_TOKEN=xxx
set DISCORD_CHANNEL_ID=xxx
set MY_DISCORD_USER_ID=xxx
set SKILLS_DIR=.skills
set OLLAMA_MODEL=qwen2.5:7b
set EMBEDDING_MODEL=nomic-embed-text
python main.py --days 7 >> skill_updater.log 2>&1
```

Task Scheduler → Create Basic Task → Weekly, Monday 9:00 AM → point to `run.bat`

---

## Why This Matters

**The problem:** Team knowledge lives in Discord but never makes it into docs and skills.
**The result:** New team members get lost, decisions repeat, standards drift.
**No manual documentation burden.** Knowledge captured at moment of discussion.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No messages found` | Check `MY_DISCORD_USER_ID`. Try `--days 30`. |
| `Discord 403` | Bot lacks Read Message History in that channel. |
| `Cannot reach Ollama` | Run `ollama serve` first. |
| `JSON parse failed` | Model returned non-JSON. Try a larger/better model. Raw response saved to `skill_updater_raw_response.txt`. |
| `replace: find text not found` | LLM hallucinated the text. Review `skill_updater_raw_response.txt` and apply manually. |
| Embeddings slow | Use `nomic-embed-text` (pull with `ollama pull nomic-embed-text`). |

---

## Tips

- Use `--dry-run` first when testing a new model.
- After a `--dry-run`, review the JSON in the output and adjust `RELEVANCE_THRESHOLD`
  if too many / too few files are being included.
- For large skill folders, a dedicated embedding model (`nomic-embed-text`) is much
  faster than using your generation model for embeddings.
- Commit your `skills/` folder to git — that way bad patches are one `git diff` away
  from being reviewed and one `git checkout` from being reverted.