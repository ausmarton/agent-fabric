"""File tools scoped to sandbox."""

from __future__ import annotations

from .sandbox import SandboxPolicy, safe_path


def read_text(policy: SandboxPolicy, rel_path: str) -> dict:
    p = safe_path(policy, rel_path)
    return {"path": rel_path, "content": p.read_text(encoding="utf-8")}


def write_text(policy: SandboxPolicy, rel_path: str, content: str) -> dict:
    p = safe_path(policy, rel_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"path": rel_path, "bytes": len(content.encode("utf-8"))}


def list_tree(policy: SandboxPolicy, max_files: int = 500) -> dict:
    root = policy.root.resolve()
    files = []
    for p in root.rglob("*"):
        if p.is_file():
            files.append(str(p.relative_to(root)))
            if len(files) >= max_files:
                break
    return {"count": len(files), "files": sorted(files)}
