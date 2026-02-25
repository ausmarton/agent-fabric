"""Global capability-keyword mapping for Phase 2 capability-based routing.

A *capability* is a named unit of what a specialist pack can do (e.g.
``"code_execution"``, ``"systematic_review"``).  Each entry maps a capability
ID to a list of keywords: when any keyword appears as a substring in the
lowercased task prompt, that capability is considered *required*.

Design notes
------------
- Keywords are checked as substrings, so multi-word phrases like
  ``"systematic review"`` act as phrase matches.
- Keep keywords specific enough to avoid false positives; prefer phrases over
  single generic words (e.g. ``"run script"`` rather than ``"run"``).
- Add new capability IDs here when new specialist packs are created; update
  ``SpecialistConfig.capabilities`` in ``DEFAULT_CONFIG`` accordingly.
"""

from __future__ import annotations

from typing import Dict, List

CAPABILITY_KEYWORDS: Dict[str, List[str]] = {
    # Engineering / software-development capabilities
    "code_execution": [
        "build", "implement", "code", "service", "pipeline",
        "kubernetes", "gcp", "scala", "rust", "python", "deploy",
        "compile", "develop", "program", "script",
    ],
    "software_testing": [
        "test", "pytest", "unittest", "spec", "coverage", "tdd",
        "integration test", "unit test",
    ],
    "file_io": [
        "read file", "write file", "create file", "list files",
    ],

    # Research capabilities
    "systematic_review": [
        "literature", "systematic review", "paper", "arxiv", "survey",
        "bibliography", "citations",
    ],
    "citation_extraction": [
        "citations", "references", "bibliography",
    ],
    "web_search": [
        "search the web", "web search", "fetch url", "browse the internet",
    ],

    # Enterprise search capabilities (P7-2 / P7-3)
    "github_search": [
        "github issue", "github pr", "github pull request", "github repository",
        "search github", "github code", "github commit",
    ],
    "enterprise_search": [
        "confluence", "jira", "rally", "internal docs", "knowledge base",
        "enterprise search", "internal knowledge", "company wiki",
        "supply management", "internal policies",
    ],
}
