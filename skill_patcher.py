"""
skill_patcher.py — Load skill/reference files, score relevance, apply edits in place.

Skills folder layout (example):
  skills/
    skill.md               ← primary file, always included
    references/
      gsoc-tips.md
      tech-stack.md
    scripts/
      setup.py

Relevance scoring:
  - Embed all your Discord messages (concatenated) → one query vector
  - Embed the first chunk of each file → file vector
  - Keep files whose cosine similarity to the query is above RELEVANCE_THRESHOLD
  - skill.md (or the first .md found) is ALWAYS included regardless of score

Edit operations (from the LLM JSON):
  append_section  — add a new ## header + content block at the end of a file
  replace         — find-and-replace one occurrence of an exact string in a file
  append_end      — append raw content at the very end of a file
  create          — write a brand-new file (for new reference files)
"""
import json
from pathlib import Path

import config
import ollama_client as ollama

# How many characters of a file to embed for relevance scoring.
# Larger = more accurate but slower.  2000 chars ≈ ~500 tokens, enough for a summary.
_EMBED_WINDOW = 2000


# ── File loading ──────────────────────────────────────────────────────────────

def load_skills_folder() -> dict[str, str]:
    """
    Recursively scan SKILLS_DIR and return {relative_path: content} for all
    readable files with recognised extensions.  Files over MAX_FILE_BYTES are
    truncated with a warning note appended.
    """
    root = Path(config.SKILLS_DIR)
    if not root.exists():
        print(f"[Skills] Directory not found: {config.SKILLS_DIR}")
        return {}

    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in config.ALL_SCAN_EXTENSIONS:
            continue

        rel = str(path.relative_to(root))
        try:
            raw = path.read_bytes()
        except Exception as e:
            print(f"[Skills] Cannot read {rel}: {e}")
            continue

        if len(raw) > config.MAX_FILE_BYTES:
            content  = raw[:config.MAX_FILE_BYTES].decode("utf-8", errors="ignore")
            content += f"\n\n[...file truncated at {config.MAX_FILE_BYTES} bytes for context...]"
            print(f"[Skills] {rel} truncated ({len(raw)} bytes > {config.MAX_FILE_BYTES})")
        else:
            content = raw.decode("utf-8", errors="ignore")

        files[rel] = content

    print(f"[Skills] Loaded {len(files)} file(s) from '{config.SKILLS_DIR}'")
    return files


def _find_primary(files: dict[str, str]) -> str | None:
    """Return the relative path of the primary skill.md, or None if not found."""
    candidates = ["skill.md", "aossie_template.md"]
    for name in files:
        if name.lower() in candidates or name.lower().endswith("/skill.md"):
            return name
    # Fallback: first .md file alphabetically
    for name in sorted(files):
        if name.lower().endswith(".md"):
            return name
    return None


# ── Relevance scoring ─────────────────────────────────────────────────────────

def find_relevant_files(
    messages: list[dict],
    all_files: dict[str, str],
) -> dict[str, str]:
    """
    Return the subset of `all_files` that is relevant to the given messages.

    Algorithm:
      1. Concatenate all message contents → embed → query vector
      2. For each file, embed its first _EMBED_WINDOW chars → file vector
      3. Keep files with cosine similarity >= RELEVANCE_THRESHOLD
      4. Always keep the primary skill file regardless of score
      5. If embedding fails entirely, return ALL files (safe fallback)
    """
    if not all_files:
        return {}

    primary = _find_primary(all_files)
    if primary:
        print(f"[Embed] Primary skill file: {primary} (always included)")

    # Build query vector from all messages
    query_text = "\n".join(m["content"] for m in messages if m.get("content"))
    query_vec  = ollama.embed(query_text[:_EMBED_WINDOW * 3])  # more context for query

    if not query_vec:
        # Embedding unavailable — include everything and warn
        print("[Embed] Fallback: including all files (embedding unavailable)")
        return dict(all_files)

    relevant: dict[str, str] = {}
    print(f"[Embed] Scoring {len(all_files)} files (threshold={config.RELEVANCE_THRESHOLD})...")

    for name, content in all_files.items():
        # Primary file is unconditionally included
        if name == primary:
            relevant[name] = content
            print(f"  {name:<45} PRIMARY ✓")
            continue

        file_vec = ollama.embed(content[:_EMBED_WINDOW])
        sim      = ollama.cosine(query_vec, file_vec)
        symbol   = "✓" if sim >= config.RELEVANCE_THRESHOLD else "✗"
        print(f"  {name:<45} sim={sim:.3f} {symbol}")

        if sim >= config.RELEVANCE_THRESHOLD:
            relevant[name] = content

    print(f"[Embed] {len(relevant)}/{len(all_files)} files selected")
    return relevant


# ── Edit application ──────────────────────────────────────────────────────────

def apply_edits(edits: list[dict]) -> tuple[int, int]:
    """
    Apply a list of edit operations directly to files on disk.

    Returns (applied_count, failed_count).

    Supported operations
    --------------------
    append_section
        Adds a new markdown section (## header + content) at the end of `file`.
        Required fields: file, header, content

    replace
        Replaces the FIRST occurrence of `find` with `replace` in `file`.
        `find` must match the file content exactly (copy-paste from the skill file).
        Required fields: file, find, replace

    append_end
        Appends `content` verbatim at the end of `file`.
        Required fields: file, content

    create
        Writes a brand-new file.  Parent directories are created automatically.
        Required fields: file, content
    """
    root    = Path(config.SKILLS_DIR)
    applied = 0
    failed  = 0

    for i, op in enumerate(edits, 1):
        fname  = (op.get("file") or "").strip()
        action = (op.get("action") or "").strip()

        if not fname or not action:
            print(f"  [Edit {i}] SKIP — missing 'file' or 'action' field")
            failed += 1
            continue

        fpath = root / fname
        label = f"[Edit {i}] {action} → {fname}"

        try:
            # ── create ────────────────────────────────────────────────────
            if action == "create":
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(op.get("content", ""), encoding="utf-8")
                print(f"  {label}  ✓ created")
                applied += 1

            # ── append_section ────────────────────────────────────────────
            elif action == "append_section":
                header  = (op.get("header") or "").strip()
                content = (op.get("content") or "").strip()
                if not header or not content:
                    print(f"  {label}  ✗ missing header or content")
                    failed += 1
                    continue

                existing = fpath.read_text(encoding="utf-8") if fpath.exists() else ""

                # Guard: don't append if this header already exists
                if header in existing:
                    print(f"  {label}  ✗ header already exists, skipping")
                    failed += 1
                    continue

                block   = f"\n\n{header}\n{content}\n"
                updated = existing.rstrip() + block
                fpath.write_text(updated, encoding="utf-8")
                print(f"  {label}  ✓")
                applied += 1

            # ── append_end ────────────────────────────────────────────────
            elif action == "append_end":
                content  = op.get("content", "")
                existing = fpath.read_text(encoding="utf-8") if fpath.exists() else ""
                updated  = existing.rstrip() + "\n\n" + content.strip() + "\n"
                fpath.write_text(updated, encoding="utf-8")
                print(f"  {label}  ✓")
                applied += 1

            # ── replace ───────────────────────────────────────────────────
            elif action == "replace":
                find_text    = op.get("find", "")
                replace_text = op.get("replace", "")

                if not find_text:
                    print(f"  {label}  ✗ 'find' is empty")
                    failed += 1
                    continue
                if not fpath.exists():
                    print(f"  {label}  ✗ file does not exist")
                    failed += 1
                    continue

                existing = fpath.read_text(encoding="utf-8")
                if find_text not in existing:
                    print(f"  {label}  ✗ 'find' text not found in file — skipping")
                    failed += 1
                    continue

                updated = existing.replace(find_text, replace_text, 1)
                fpath.write_text(updated, encoding="utf-8")
                print(f"  {label}  ✓")
                applied += 1

            else:
                print(f"  {label}  ✗ unknown action")
                failed += 1

        except Exception as e:
            print(f"  {label}  ✗ error: {e}")
            failed += 1

    return applied, failed