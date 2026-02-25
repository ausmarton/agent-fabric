"""Append-only run log (events to runlog.jsonl)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict


def append_event(
    run_dir: str | Path,
    kind: str,
    payload: Dict[str, Any],
    step: str | None = None,
) -> None:
    """Append one event record to runlog.jsonl in the given run directory."""
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    log_path = run_path / "runlog.jsonl"
    record = {"ts": time.time(), "kind": kind, "step": step, "payload": payload}
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
