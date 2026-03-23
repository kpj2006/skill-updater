"""
config.py — All environment variables and validation for skill_updater.
"""
import os
import sys


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

# ── Discord ────────────────────────────────────────────────────────────────
DISCORD_BOT_TOKEN  = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "")
MY_USER_ID         = os.environ.get("MY_DISCORD_USER_ID", "")

# ── Skill files ────────────────────────────────────────────────────────────
# Root folder containing skill.md, references/, scripts/, etc.
# Backward-compatible with older SKILL_FILE env names used as a directory path.
SKILLS_DIR = os.environ.get("SKILLS_DIR") or os.environ.get("SKILL_FILE", "./.skills")

# Extensions treated as editable skill/reference documents
SKILL_DOC_EXTENSIONS = {".md", ".txt"}

# Extensions scanned for context but only edited if LLM explicitly targets them
ALL_SCAN_EXTENSIONS  = {".md", ".txt", ".py", ".js", ".ts", ".yaml", ".yml", ".json"}

# Skip files larger than this (bytes) — avoids sending huge scripts to Ollama
MAX_FILE_BYTES = int(os.environ.get("MAX_FILE_BYTES", 60_000))

# ── Ollama ─────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL  = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL     = os.environ.get("OLLAMA_MODEL", "llama3")

# Embedding model — often lighter than the generation model, e.g. nomic-embed-text
EMBEDDING_MODEL  = os.environ.get("EMBEDDING_MODEL", OLLAMA_MODEL)

# Cosine similarity threshold: files scoring above this are included in the prompt
RELEVANCE_THRESHOLD = float(os.environ.get("RELEVANCE_THRESHOLD", "0.30"))

# ── Misc ───────────────────────────────────────────────────────────────────
LOG_FILE     = os.environ.get("LOG_FILE", "skill_updater.log")
RAW_LOG_FILE = "skill_updater_raw_response.txt"  # saved on JSON-parse failure

REQUIRED_VARS = [
    ("DISCORD_BOT_TOKEN",  DISCORD_BOT_TOKEN),
    ("DISCORD_CHANNEL_ID", DISCORD_CHANNEL_ID),
    ("MY_DISCORD_USER_ID", MY_USER_ID),
]


def validate():
    missing = [name for name, val in REQUIRED_VARS if not val]
    if missing:
        print(f"[ERROR] Missing required environment variables: {', '.join(missing)}")
        print("        Set them in your .env file or export before running.")
        sys.exit(1)