"""Persistent cross-run index: lightweight JSONL record of all successful runs.

Each successful run appends one line to ``{workspace_root}/run_index.jsonl``.
The index enables fast search over past runs without scanning individual
runlog.jsonl files.

**Search modes:**

- **Keyword (default):** ``search_index()`` — case-insensitive substring match
  on ``prompt_prefix`` and ``summary``.  No extra deps; always works.
- **Semantic (P7-1):** ``semantic_search_index()`` — embeds query + entries via
  Ollama ``/api/embeddings``; ranks by cosine similarity.  Requires an embedding
  model to be configured (``RunIndexConfig.embedding_model``) and the entries to
  have been embedded at write time.  Falls back to keyword search when embeddings
  are missing or unavailable.

Format: one JSON object per line, fields defined by ``RunIndexEntry``.
Reader skips malformed lines gracefully.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RunIndexEntry:
    """One record in the run index — written once per successful run."""

    run_id: str
    timestamp: float           # Unix epoch seconds (from run start)
    specialist_ids: List[str]  # all specialists that ran (task force aware)
    prompt_prefix: str         # first 200 chars of the original task prompt
    summary: str               # payload["summary"] or payload["executive_summary"]
    workspace_path: str        # path to the run's workspace dir
    run_dir: str               # path to the run directory (contains runlog.jsonl)
    routing_method: str = ""   # "explicit", "llm", "keyword", …
    model_name: str = ""       # model used for the task
    # P7-1: optional embedding vector for semantic search.
    # None = not embedded (keyword-only entry); list[float] = embedded.
    embedding: Optional[List[float]] = field(default=None)


def append_to_index(workspace_root: str, entry: RunIndexEntry) -> None:
    """Append *entry* to the run index JSONL file.

    Creates the index file (and parent directories) if they don't exist.
    Uses line-level appends — safe for single-writer local CLI usage.
    A corrupt partial write is silently skipped by the reader (which
    already tolerates malformed JSONL lines in runlog files).

    When ``entry.embedding`` is not None the embedding vector is included
    in the serialised record so that ``semantic_search_index()`` can later
    rank entries without re-embedding them.
    """
    index_path = Path(workspace_root) / "run_index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(entry), ensure_ascii=False)
    with open(index_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    logger.debug("RunIndex: appended run %s to %s", entry.run_id, index_path)


def search_index(
    workspace_root: str,
    query: str,
    limit: int = 20,
) -> List[RunIndexEntry]:
    """Return entries whose ``prompt_prefix`` or ``summary`` contain *query*.

    Matching is case-insensitive substring search.  Returns at most
    ``limit`` entries sorted most-recent-first.  Returns an empty list
    (not an error) when the index file does not exist.
    """
    index_path = Path(workspace_root) / "run_index.jsonl"
    if not index_path.is_file():
        return []

    q = query.lower()
    entries: List[RunIndexEntry] = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        if q in data.get("prompt_prefix", "").lower() or q in data.get("summary", "").lower():
            entries.append(_entry_from_dict(data))

    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return entries[:limit]


# ---------------------------------------------------------------------------
# Semantic search (P7-1)
# ---------------------------------------------------------------------------

async def embed_text(text: str, model: str, base_url: str) -> List[float]:
    """Embed *text* using the Ollama ``/api/embeddings`` endpoint.

    Args:
        text: Text to embed.
        model: Embedding model name (e.g. ``"nomic-embed-text"``).
        base_url: Ollama base URL.  Any ``/v1`` or ``/v1/`` suffix is stripped
            before appending ``/api/embeddings`` — so both
            ``"http://localhost:11434/v1"`` and ``"http://localhost:11434"``
            work correctly.

    Returns:
        Float list (the embedding vector).

    Raises:
        httpx.HTTPStatusError: When the embedding call returns a non-2xx status.
        httpx.RequestError: On connection failure.
    """
    import httpx

    # Normalise: strip trailing /v1 (or /v1/) so we get the Ollama root URL.
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    embeddings_url = normalized.rstrip("/") + "/api/embeddings"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            embeddings_url,
            json={"model": model, "prompt": text},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two equal-length float vectors.

    Returns 0.0 for zero vectors (avoids division by zero).
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def semantic_search_index(
    workspace_root: str,
    query: str,
    embedding_model: str,
    embedding_base_url: str,
    top_k: int = 10,
) -> List[RunIndexEntry]:
    """Return top-k entries ranked by cosine similarity to *query*.

    Algorithm:
    1. Load all entries from the JSONL index.
    2. Filter to those that have an ``embedding`` field (set at write time when
       ``RunIndexConfig.embedding_model`` is configured).
    3. Embed *query* via Ollama ``/api/embeddings``.
    4. Rank by cosine similarity; return top-k.

    Falls back to ``search_index()`` (keyword) when:
    - No entries have embeddings (index was built without a configured model).
    - The embedding call fails (e.g. model not pulled, server unreachable).

    Args:
        workspace_root: Directory containing ``run_index.jsonl``.
        query: Free-text search query.
        embedding_model: Ollama model name to use for embedding.
        embedding_base_url: Ollama base URL passed to ``embed_text()``.
        top_k: Maximum number of results to return.

    Returns:
        List of ``RunIndexEntry`` sorted by descending similarity (or keyword
        relevance as fallback).
    """
    index_path = Path(workspace_root) / "run_index.jsonl"
    if not index_path.is_file():
        return []

    all_entries: List[RunIndexEntry] = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        all_entries.append(_entry_from_dict(data))

    if not all_entries:
        return []

    # Only entries that were embedded at write time can be ranked semantically.
    entries_with_embeddings = [e for e in all_entries if e.embedding]
    if not entries_with_embeddings:
        logger.debug(
            "semantic_search_index: no entries with embeddings; falling back to keyword search"
        )
        return search_index(workspace_root, query, limit=top_k)

    # Embed the query.
    try:
        query_embedding = await embed_text(query, embedding_model, embedding_base_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "semantic_search_index: embed_text failed (%s); falling back to keyword search", exc
        )
        return search_index(workspace_root, query, limit=top_k)

    # Score and rank.
    scored = [
        (cosine_similarity(query_embedding, entry.embedding), entry)  # type: ignore[arg-type]
        for entry in entries_with_embeddings
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [entry for _, entry in scored[:top_k]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry_from_dict(data: dict) -> RunIndexEntry:
    """Construct a RunIndexEntry from a raw dict, tolerating missing/extra keys."""
    raw_embedding = data.get("embedding")
    embedding: Optional[List[float]]
    if isinstance(raw_embedding, list) and raw_embedding:
        try:
            embedding = [float(x) for x in raw_embedding]
        except (TypeError, ValueError):
            embedding = None
    else:
        embedding = None

    return RunIndexEntry(
        run_id=str(data.get("run_id", "")),
        timestamp=float(data.get("timestamp", 0.0)),
        specialist_ids=list(data.get("specialist_ids", [])),
        prompt_prefix=str(data.get("prompt_prefix", "")),
        summary=str(data.get("summary", "")),
        workspace_path=str(data.get("workspace_path", "")),
        run_dir=str(data.get("run_dir", "")),
        routing_method=str(data.get("routing_method", "")),
        model_name=str(data.get("model_name", "")),
        embedding=embedding,
    )
