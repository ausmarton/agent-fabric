"""Tests for ChromaRunIndex and ChromaDB dispatch in run_index.py.

All chromadb calls are mocked via sys.modules injection — chromadb does not
need to be installed for these tests to pass.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentic_concierge.infrastructure.workspace.run_index import (
    RunIndexEntry,
    append_to_index,
    semantic_search_index,
)
from agentic_concierge.config.schema import RunIndexConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(run_id: str = "run-1") -> RunIndexEntry:
    return RunIndexEntry(
        run_id=run_id,
        timestamp=1000.0,
        specialist_ids=["engineering"],
        prompt_prefix="Build a service",
        summary="Built a FastAPI service",
        workspace_path="/ws",
        run_dir="/ws/runs/run-1",
        routing_method="keyword",
        model_name="qwen2.5:7b",
        embedding=[0.1, 0.2, 0.3],
    )


def _make_collection_mock(count: int = 1) -> MagicMock:
    """Return a mock ChromaDB collection."""
    col = MagicMock()
    col.count.return_value = count
    col.upsert = MagicMock()
    col.query.return_value = {
        "metadatas": [[{
            "run_id": "run-1",
            "timestamp": 1000.0,
            "specialist_ids": "engineering",
            "prompt_prefix": "Build a service",
            "summary": "Built a FastAPI service",
            "workspace_path": "/ws",
            "run_dir": "/ws/runs/run-1",
            "routing_method": "keyword",
            "model_name": "qwen2.5:7b",
        }]],
    }
    return col


def _mock_chromadb(collection_mock: MagicMock) -> MagicMock:
    """Build a mock chromadb module with a PersistentClient that uses the given collection."""
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = collection_mock
    mock_chromadb_mod = MagicMock()
    mock_chromadb_mod.PersistentClient.return_value = mock_client
    return mock_chromadb_mod


# ---------------------------------------------------------------------------
# ChromaRunIndex.add
# ---------------------------------------------------------------------------

def test_add_calls_upsert_with_correct_fields(tmp_path):
    # Import is lazy (inside __init__), so we inject a mock chromadb module.
    mock_col = _make_collection_mock()
    mock_chromadb_mod = _mock_chromadb(mock_col)

    with patch.dict(sys.modules, {"chromadb": mock_chromadb_mod}):
        from agentic_concierge.infrastructure.workspace.run_index_chroma import ChromaRunIndex
        idx = ChromaRunIndex(str(tmp_path))

    entry = _make_entry("run-abc")
    idx.add(entry, [0.1, 0.2, 0.3])

    mock_col.upsert.assert_called_once()
    call_kwargs = mock_col.upsert.call_args
    assert call_kwargs.kwargs["ids"] == ["run-abc"]
    assert call_kwargs.kwargs["embeddings"] == [[0.1, 0.2, 0.3]]
    meta = call_kwargs.kwargs["metadatas"][0]
    assert meta["run_id"] == "run-abc"
    assert meta["specialist_ids"] == "engineering"


# ---------------------------------------------------------------------------
# ChromaRunIndex.search
# ---------------------------------------------------------------------------

def test_search_returns_entries(tmp_path):
    mock_col = _make_collection_mock(count=1)
    mock_chromadb_mod = _mock_chromadb(mock_col)

    with patch.dict(sys.modules, {"chromadb": mock_chromadb_mod}):
        from agentic_concierge.infrastructure.workspace.run_index_chroma import ChromaRunIndex
        idx = ChromaRunIndex(str(tmp_path))

    results = idx.search([0.1, 0.2, 0.3], top_k=5)

    assert len(results) == 1
    assert results[0].run_id == "run-1"
    assert results[0].specialist_ids == ["engineering"]


def test_search_empty_collection_returns_empty_list(tmp_path):
    mock_col = _make_collection_mock(count=0)
    mock_chromadb_mod = _mock_chromadb(mock_col)

    with patch.dict(sys.modules, {"chromadb": mock_chromadb_mod}):
        from agentic_concierge.infrastructure.workspace.run_index_chroma import ChromaRunIndex
        idx = ChromaRunIndex(str(tmp_path))

    results = idx.search([0.1, 0.2, 0.3])

    assert results == []
    mock_col.query.assert_not_called()


def test_search_limits_n_results_to_collection_count(tmp_path):
    mock_col = _make_collection_mock(count=2)
    mock_col.query.return_value = {
        "metadatas": [[
            {
                "run_id": "run-1", "timestamp": 1.0, "specialist_ids": "engineering",
                "prompt_prefix": "x", "summary": "y", "workspace_path": "/ws",
                "run_dir": "/ws/runs/run-1", "routing_method": "", "model_name": "",
            },
            {
                "run_id": "run-2", "timestamp": 2.0, "specialist_ids": "research",
                "prompt_prefix": "a", "summary": "b", "workspace_path": "/ws2",
                "run_dir": "/ws2/runs/run-2", "routing_method": "", "model_name": "",
            },
        ]],
    }
    mock_chromadb_mod = _mock_chromadb(mock_col)

    with patch.dict(sys.modules, {"chromadb": mock_chromadb_mod}):
        from agentic_concierge.infrastructure.workspace.run_index_chroma import ChromaRunIndex
        idx = ChromaRunIndex(str(tmp_path))

    results = idx.search([0.1, 0.2, 0.3], top_k=100)

    # n_results capped at collection count (2)
    mock_col.query.assert_called_once()
    call_kwargs = mock_col.query.call_args
    assert call_kwargs.kwargs["n_results"] == 2
    assert len(results) == 2


# ---------------------------------------------------------------------------
# append_to_index with ChromaDB provider
# ---------------------------------------------------------------------------

def test_append_to_index_chromadb_provider_calls_chroma(tmp_path):
    entry = _make_entry()
    cfg = RunIndexConfig(provider="chromadb", chromadb_collection="test_col")

    mock_col = _make_collection_mock()
    mock_chromadb_mod = _mock_chromadb(mock_col)

    with patch.dict(sys.modules, {"chromadb": mock_chromadb_mod}):
        with patch(
            "agentic_concierge.infrastructure.workspace.run_index._resolve_chromadb_path",
            return_value=str(tmp_path / "chroma"),
        ):
            append_to_index(str(tmp_path), entry, run_index_config=cfg)

    # JSONL was written
    assert (tmp_path / "run_index.jsonl").exists()
    # ChromaDB upsert was called (via PersistentClient mock chain)
    mock_col.upsert.assert_called_once()


def test_append_to_index_jsonl_provider_skips_chroma(tmp_path):
    entry = _make_entry()
    cfg = RunIndexConfig(provider="jsonl")

    with patch(
        "agentic_concierge.infrastructure.workspace.run_index_chroma.ChromaRunIndex",
    ) as mock_cls:
        append_to_index(str(tmp_path), entry, run_index_config=cfg)
        mock_cls.assert_not_called()

    assert (tmp_path / "run_index.jsonl").exists()


def test_append_to_index_no_embedding_skips_chroma(tmp_path):
    """When provider=chromadb but entry has no embedding, ChromaDB is NOT called."""
    entry = RunIndexEntry(
        run_id="run-x",
        timestamp=1.0,
        specialist_ids=["engineering"],
        prompt_prefix="test",
        summary="test",
        workspace_path="/ws",
        run_dir="/ws/runs/run-x",
        embedding=None,  # no embedding
    )
    cfg = RunIndexConfig(provider="chromadb")

    with patch(
        "agentic_concierge.infrastructure.workspace.run_index_chroma.ChromaRunIndex",
    ) as mock_cls:
        append_to_index(str(tmp_path), entry, run_index_config=cfg)
        mock_cls.assert_not_called()


def test_append_to_index_no_config_uses_jsonl_only(tmp_path):
    """Calling without run_index_config (default None) writes JSONL only."""
    entry = _make_entry()
    with patch(
        "agentic_concierge.infrastructure.workspace.run_index_chroma.ChromaRunIndex",
    ) as mock_cls:
        append_to_index(str(tmp_path), entry)  # no run_index_config
        mock_cls.assert_not_called()

    assert (tmp_path / "run_index.jsonl").exists()


# ---------------------------------------------------------------------------
# semantic_search_index with ChromaDB provider
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_semantic_search_chromadb_provider_uses_chroma(tmp_path):
    cfg = RunIndexConfig(provider="chromadb", chromadb_collection="test_col")
    fake_embedding = [0.1, 0.2, 0.3]
    fake_entry = _make_entry()

    mock_col = _make_collection_mock(count=1)
    mock_chromadb_mod = _mock_chromadb(mock_col)
    # Make search return our fake entry
    mock_col.query.return_value = {
        "metadatas": [[{
            "run_id": fake_entry.run_id,
            "timestamp": fake_entry.timestamp,
            "specialist_ids": ",".join(fake_entry.specialist_ids),
            "prompt_prefix": fake_entry.prompt_prefix,
            "summary": fake_entry.summary,
            "workspace_path": fake_entry.workspace_path,
            "run_dir": fake_entry.run_dir,
            "routing_method": fake_entry.routing_method,
            "model_name": fake_entry.model_name,
        }]],
    }

    with patch(
        "agentic_concierge.infrastructure.workspace.run_index.embed_text",
        new=AsyncMock(return_value=fake_embedding),
    ):
        with patch(
            "agentic_concierge.infrastructure.workspace.run_index._resolve_chromadb_path",
            return_value=str(tmp_path / "chroma"),
        ):
            with patch.dict(sys.modules, {"chromadb": mock_chromadb_mod}):
                results = await semantic_search_index(
                    str(tmp_path),
                    "build a service",
                    embedding_model="nomic-embed-text",
                    embedding_base_url="http://localhost:11434",
                    run_index_config=cfg,
                )

    assert len(results) == 1
    assert results[0].run_id == fake_entry.run_id
    mock_col.query.assert_called_once()


@pytest.mark.asyncio
async def test_semantic_search_chromadb_falls_back_on_exception(tmp_path):
    """When ChromaDB search raises, fall back to JSONL keyword search."""
    cfg = RunIndexConfig(provider="chromadb")

    # Write a JSONL entry so keyword search can return something
    import json
    from dataclasses import asdict
    entry = _make_entry()
    idx_path = tmp_path / "run_index.jsonl"
    idx_path.write_text(json.dumps(asdict(entry)) + "\n", encoding="utf-8")

    with patch(
        "agentic_concierge.infrastructure.workspace.run_index.embed_text",
        new=AsyncMock(side_effect=RuntimeError("chromadb down")),
    ):
        results = await semantic_search_index(
            str(tmp_path),
            "build",
            embedding_model="nomic-embed-text",
            embedding_base_url="http://localhost:11434",
            run_index_config=cfg,
        )

    # Should have fallen back to keyword search
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# _resolve_chromadb_path
# ---------------------------------------------------------------------------

def test_resolve_chromadb_path_uses_explicit_path(tmp_path):
    from agentic_concierge.infrastructure.workspace.run_index import _resolve_chromadb_path

    cfg = RunIndexConfig(provider="chromadb", chromadb_path=str(tmp_path / "my_chroma"))
    result = _resolve_chromadb_path(cfg)
    assert result == str(tmp_path / "my_chroma")


def test_resolve_chromadb_path_empty_uses_platformdirs():
    from agentic_concierge.infrastructure.workspace.run_index import _resolve_chromadb_path

    cfg = RunIndexConfig(provider="chromadb", chromadb_path="")
    result = _resolve_chromadb_path(cfg)
    assert "agentic-concierge" in result or "chromadb" in result
