# skill_updater v2

Analyses your own Discord messages, scores skill/reference files for relevance
using Ollama embeddings, then **auto-patches** your skill files in place.
No confirmation prompts. No separate suggestions file. Changes go straight in.

```
Discord messages
      │
      ▼  noise filter
      │
      ▼  Ollama embeddings  ←── skills/ folder
      │  (relevance score)
      │
      ▼  Ollama generation  ←── relevant files + messages
      │  (structured JSON)
      │
      ▼  skill_patcher
         writes edits directly to skill.md + reference files
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

- Python 3.10+  (uses `X | Y` type hints)
- Ollama running locally — `ollama serve`
- A Discord bot with **Read Message History** in your target channel

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