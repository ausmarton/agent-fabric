"""Persistent cross-run index: lightweight JSONL record of all successful runs.

Each successful run appends one line to ``{workspace_root}/run_index.jsonl``.
The index enables fast keyword search over past runs without scanning
individual runlog.jsonl files, and provides a foundation for richer
retrieval (vector search, embedding-based similarity) in later phases.

Format: one JSON object per line, fields defined by ``RunIndexEntry``.
Reader skips malformed lines gracefully.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List

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


def append_to_index(workspace_root: str, entry: RunIndexEntry) -> None:
    """Append *entry* to the run index JSONL file.

    Creates the index file (and parent directories) if they don't exist.
    Uses line-level appends — safe for single-writer local CLI usage.
    A corrupt partial write is silently skipped by the reader (which
    already tolerates malformed JSONL lines in runlog files).
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


def _entry_from_dict(data: dict) -> RunIndexEntry:
    """Construct a RunIndexEntry from a raw dict, tolerating missing/extra keys."""
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
    )
