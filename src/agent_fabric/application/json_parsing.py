"""Extract a single JSON object from model output (best-effort)."""

from __future__ import annotations

import json
from typing import Any


def extract_json(text: str) -> tuple[bool, Any, str]:
    """
    Try to parse a top-level JSON object from text.
    Returns (ok, parsed_value, error_message).
    """
    try:
        return True, json.loads(text), ""
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return False, None, "No JSON object found"
    try:
        return True, json.loads(text[start : end + 1]), ""
    except Exception as e:
        return False, None, f"Failed to parse JSON: {e}"
