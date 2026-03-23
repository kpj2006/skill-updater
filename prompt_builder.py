"""
prompt_builder.py — Construct the Ollama prompt that asks for structured JSON edits.

Design decisions
----------------
- The model is instructed to output ONLY valid JSON (no markdown fences,
  no preamble).  This makes auto-patching reliable without brittle regex.
- The JSON schema is explicit and includes examples so even smaller models
  (7B/13B) tend to follow it.
- We include the full content of all relevant files so the model can reason
  about what already exists before suggesting changes.
- For large skill folders, we include a "file index" summary first, then
  the full content — this helps the model orient before reading details.
"""
from datetime import datetime


def _format_messages(messages: list[dict]) -> str:
    """Format Discord messages for the prompt, including reply context."""
    lines = []
    for m in messages:
        if m.get("reply_to"):
            lines.append(f"  ↩ replying to → {m['reply_to']}")
        lines.append(f"[{m['timestamp']}] YOU: {m['content']}")
        lines.append("")
    return "\n".join(lines).strip() or "(no messages in this period)"


def _format_files(skill_files: dict[str, str]) -> str:
    """Format skill files for the prompt with clear file separators."""
    if not skill_files:
        return "(no skill files found)"

    # File index at the top so the model sees the structure first
    index = "Files included:\n" + "\n".join(f"  - {name}" for name in skill_files)

    sections = [index, ""]
    for name, content in skill_files.items():
        sections.append(f"{'─'*60}")
        sections.append(f"FILE: {name}")
        sections.append(f"{'─'*60}")
        sections.append(content)
        sections.append("")

    return "\n".join(sections)


def build(
    skill_files: dict[str, str],
    messages:    list[dict],
    start:       datetime,
    end:         datetime,
) -> str:
    """
    Build and return the full prompt string to send to Ollama.
    """
    msg_text  = _format_messages(messages)
    files_text = _format_files(skill_files)

    # Build a comma-separated list of known filenames so the model references
    # them correctly in its output.
    known_files = ", ".join(f'"{n}"' for n in skill_files) or '"skill.md"'

    return f"""You are a skill documentation maintainer for an AI Discord bot.

Your job is to analyse the maintainer's own Discord messages and update the bot's
skill/reference files so future AI responses are more accurate and useful.

═══════════════════════════════════════════════════════════════
CURRENT SKILL FILES
═══════════════════════════════════════════════════════════════
{files_text}

═══════════════════════════════════════════════════════════════
MAINTAINER'S DISCORD MESSAGES  ({start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')})
═══════════════════════════════════════════════════════════════
{msg_text}

═══════════════════════════════════════════════════════════════
TASK
═══════════════════════════════════════════════════════════════
1. Identify topics, patterns, or corrections revealed by the messages that are
   NOT yet covered (or are outdated) in the skill files.
2. Produce a minimal set of targeted edits — do NOT rewrite entire files.
3. Be conservative: only suggest changes with clear evidence from the messages.

═══════════════════════════════════════════════════════════════
OUTPUT — STRICT JSON ONLY
═══════════════════════════════════════════════════════════════
Return ONLY a single valid JSON object.
No markdown fences (no ```json).  No text before or after the JSON.

Known filenames you may target: {known_files}

JSON schema:

{{
  "summary": "<2–3 sentences: what the messages reveal about skill gaps>",
  "no_changes_needed": false,
  "edits": [

    {{
      "file": "skill.md",
      "action": "append_section",
      "header": "## Exact Section Title",
      "content": "Full markdown content for this new section.\\n- bullet\\n- bullet"
    }},

    {{
      "file": "skill.md",
      "action": "replace",
      "find": "exact existing text copied verbatim from the file",
      "replace": "corrected replacement text"
    }},

    {{
      "file": "skill.md",
      "action": "append_end",
      "content": "Small addition at the bottom of the file."
    }},

    {{
      "file": "references/new-topic.md",
      "action": "create",
      "content": "# New Reference\\nFull content for a new reference file."
    }}

  ]
}}

Rules:
- Use "append_section" to introduce a new ## heading + body.
- Use "replace" to fix WRONG or OUTDATED text.  The "find" string MUST appear
  verbatim in the file — copy it exactly, including whitespace.
- Use "append_end" for small, headerless additions at the bottom.
- Use "create" only when the new content is too large/specific for skill.md itself.
- Use forward slashes in all file paths, e.g. "references/debugging.md".
- Never emit Windows backslashes in any JSON string unless they are escaped as \\\\.
- If nothing needs changing, set "no_changes_needed": true and "edits": [].
- Never include an entire file in a "replace" — only the specific changed portion.
- Produce the minimum number of edits needed.  Quality over quantity.
"""