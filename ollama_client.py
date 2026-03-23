"""
ollama_client.py — Ollama API: text generation + embeddings + cosine similarity.

All calls go through OLLAMA_BASE_URL (default: http://localhost:11434).
Embeddings use EMBEDDING_MODEL which can be a lighter model than the
generation model (e.g. nomic-embed-text vs llama3).
"""
import json
import math
import sys
import urllib.error
import urllib.request

import config

_GENERATE_URL = f"{config.OLLAMA_BASE_URL}/api/generate"
_EMBED_URL    = f"{config.OLLAMA_BASE_URL}/api/embeddings"


def _post(url: str, payload: dict, timeout: int) -> dict:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read())


def generate(prompt: str) -> str:
    """
    Send a prompt to Ollama and return the full text response.
    Timeout is generous (5 min) for large skill files + many messages.
    """
    print(f"[Ollama] Generating with model '{config.OLLAMA_MODEL}'...")
    try:
        resp = _post(_GENERATE_URL, {
            "model":  config.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
        }, timeout=300)
        return resp.get("response", "").strip()
    except urllib.error.URLError as e:
        print(f"[ERROR] Cannot reach Ollama at {config.OLLAMA_BASE_URL}: {e.reason}")
        print("        Is Ollama running?  →  ollama serve")
        sys.exit(1)


def embed(text: str) -> list[float]:
    """
    Return an embedding vector for `text`.
    Returns an empty list on failure — callers must handle this gracefully
    (typically by falling back to including all files).
    """
    try:
        resp = _post(_EMBED_URL, {
            "model":  config.EMBEDDING_MODEL,
            "prompt": text,
        }, timeout=60)
        return resp.get("embedding", [])
    except Exception as e:
        # Non-fatal: embeddings are used only for relevance filtering.
        print(f"[WARN] Embedding call failed ({e}). Relevance filter disabled.")
        return []


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors. Returns 0.0 on empty."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    return dot / (mag_a * mag_b) if mag_a and mag_b else 0.0


def embed_many(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts. Returns a parallel list of vectors (empty on failure)."""
    vectors = []
    for i, text in enumerate(texts, 1):
        vec = embed(text)
        vectors.append(vec)
        if i % 5 == 0:
            print(f"  [Embed] {i}/{len(texts)} done")
    return vectors