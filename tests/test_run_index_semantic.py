"""Tests for semantic run index search (P7-1).

All tests are unit tests — they mock httpx and file I/O so no real Ollama
embedding model is required.  Fast CI: no extra deps needed beyond httpx
(already a project dependency).
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_fabric.infrastructure.workspace.run_index import (
    RunIndexEntry,
    _entry_from_dict,
    append_to_index,
    cosine_similarity,
    embed_text,
    search_index,
    semantic_search_index,
)
from agent_fabric.config.schema import RunIndexConfig


# ---------------------------------------------------------------------------
# RunIndexEntry — embedding field
# ---------------------------------------------------------------------------


def test_entry_embedding_defaults_to_none():
    entry = RunIndexEntry(
        run_id="r1",
        timestamp=1.0,
        specialist_ids=["engineering"],
        prompt_prefix="hello",
        summary="world",
        workspace_path="/ws",
        run_dir="/ws/runs/r1",
    )
    assert entry.embedding is None


def test_entry_embedding_can_be_set():
    vec = [0.1, 0.2, 0.3]
    entry = RunIndexEntry(
        run_id="r1",
        timestamp=1.0,
        specialist_ids=["engineering"],
        prompt_prefix="hello",
        summary="world",
        workspace_path="/ws",
        run_dir="/ws/runs/r1",
        embedding=vec,
    )
    assert entry.embedding == vec


def test_entry_serializes_embedding():
    vec = [0.1, 0.2, 0.3]
    entry = RunIndexEntry(
        run_id="r1",
        timestamp=1.0,
        specialist_ids=["engineering"],
        prompt_prefix="hello",
        summary="world",
        workspace_path="/ws",
        run_dir="/ws/runs/r1",
        embedding=vec,
    )
    d = asdict(entry)
    assert d["embedding"] == vec


def test_entry_serializes_null_embedding():
    entry = RunIndexEntry(
        run_id="r1",
        timestamp=1.0,
        specialist_ids=["engineering"],
        prompt_prefix="hello",
        summary="world",
        workspace_path="/ws",
        run_dir="/ws/runs/r1",
    )
    d = asdict(entry)
    assert d["embedding"] is None


def test_entry_from_dict_deserializes_embedding():
    data = {
        "run_id": "r1",
        "timestamp": 1.0,
        "specialist_ids": ["engineering"],
        "prompt_prefix": "hello",
        "summary": "world",
        "workspace_path": "/ws",
        "run_dir": "/ws/runs/r1",
        "embedding": [0.1, 0.2, 0.3],
    }
    entry = _entry_from_dict(data)
    assert entry.embedding == [0.1, 0.2, 0.3]


def test_entry_from_dict_handles_null_embedding():
    data = {
        "run_id": "r1",
        "timestamp": 1.0,
        "specialist_ids": [],
        "prompt_prefix": "",
        "summary": "",
        "workspace_path": "",
        "run_dir": "",
        "embedding": None,
    }
    entry = _entry_from_dict(data)
    assert entry.embedding is None


def test_entry_from_dict_handles_missing_embedding():
    """Old index entries without 'embedding' key are handled gracefully."""
    data = {
        "run_id": "r1",
        "timestamp": 1.0,
        "specialist_ids": [],
        "prompt_prefix": "",
        "summary": "",
        "workspace_path": "",
        "run_dir": "",
    }
    entry = _entry_from_dict(data)
    assert entry.embedding is None


# ---------------------------------------------------------------------------
# cosine_similarity
# ---------------------------------------------------------------------------


def test_cosine_similarity_identical_vectors():
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector_returns_zero():
    a = [0.0, 0.0, 0.0]
    b = [1.0, 2.0, 3.0]
    assert cosine_similarity(a, b) == 0.0
    assert cosine_similarity(b, a) == 0.0


# ---------------------------------------------------------------------------
# embed_text — URL normalisation and HTTP interaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_text_strips_v1_suffix():
    """embed_text should call /api/embeddings, stripping /v1 from base_url."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"embedding": [0.1, 0.2]}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await embed_text("hello", "nomic-embed-text", "http://localhost:11434/v1")

    mock_client.post.assert_called_once()
    call_url = mock_client.post.call_args[0][0]
    assert call_url == "http://localhost:11434/api/embeddings"
    assert result == [0.1, 0.2]


@pytest.mark.asyncio
async def test_embed_text_works_without_v1_suffix():
    """embed_text should also work when base_url has no /v1 suffix."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"embedding": [0.5, 0.6]}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await embed_text("hello", "nomic-embed-text", "http://localhost:11434")

    call_url = mock_client.post.call_args[0][0]
    assert call_url == "http://localhost:11434/api/embeddings"
    assert result == [0.5, 0.6]


@pytest.mark.asyncio
async def test_embed_text_raises_on_http_error():
    """embed_text propagates httpx errors so the caller can log them."""
    import httpx

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("conn refused"))

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(httpx.ConnectError):
            await embed_text("hello", "nomic-embed-text", "http://localhost:11434")


# ---------------------------------------------------------------------------
# semantic_search_index
# ---------------------------------------------------------------------------


def _write_index(tmp_path: Path, entries: list[RunIndexEntry]) -> str:
    workspace = str(tmp_path)
    for entry in entries:
        append_to_index(workspace, entry)
    return workspace


def _make_entry(run_id: str, prompt: str, summary: str, embedding=None) -> RunIndexEntry:
    return RunIndexEntry(
        run_id=run_id,
        timestamp=float(run_id.lstrip("r") or "0"),
        specialist_ids=["engineering"],
        prompt_prefix=prompt,
        summary=summary,
        workspace_path=f"/ws/{run_id}",
        run_dir=f"/ws/runs/{run_id}",
        embedding=embedding,
    )


@pytest.mark.asyncio
async def test_semantic_search_returns_empty_when_no_index(tmp_path: Path):
    result = await semantic_search_index(
        str(tmp_path), "kubernetes", "nomic-embed-text", "http://localhost:11434"
    )
    assert result == []


@pytest.mark.asyncio
async def test_semantic_search_falls_back_to_keyword_when_no_embeddings(tmp_path: Path):
    """When no entries have embeddings, fall back to keyword search."""
    workspace = _write_index(tmp_path, [
        _make_entry("1", "build a kubernetes cluster", "cluster done"),
        _make_entry("2", "write a poem", "poem done"),
    ])

    result = await semantic_search_index(
        workspace, "kubernetes", "nomic-embed-text", "http://localhost:11434"
    )
    # Falls back to keyword search — should find the kubernetes entry
    assert len(result) == 1
    assert result[0].run_id == "1"


@pytest.mark.asyncio
async def test_semantic_search_falls_back_to_keyword_when_embed_text_fails(tmp_path: Path):
    """When embed_text raises, fall back to keyword search."""
    workspace = _write_index(tmp_path, [
        _make_entry("1", "build a kubernetes cluster", "cluster done", embedding=[1.0, 0.0]),
        _make_entry("2", "write a poem", "poem done", embedding=[0.0, 1.0]),
    ])

    with patch(
        "agent_fabric.infrastructure.workspace.run_index.embed_text",
        side_effect=Exception("server offline"),
    ):
        result = await semantic_search_index(
            workspace, "kubernetes", "nomic-embed-text", "http://localhost:11434"
        )

    # Falls back to keyword; "kubernetes" matches entry 1
    assert len(result) == 1
    assert result[0].run_id == "1"


@pytest.mark.asyncio
async def test_semantic_search_ranks_by_cosine_similarity(tmp_path: Path):
    """When embeddings are present, results are ranked by cosine similarity."""
    # Entry "1" is in direction [1, 0]; entry "2" is in direction [0, 1].
    # Query embedding is [0.9, 0.1] — should rank entry "1" first.
    workspace = _write_index(tmp_path, [
        _make_entry("1", "kubernetes cluster", "cluster done", embedding=[1.0, 0.0]),
        _make_entry("2", "write a poem", "poem done", embedding=[0.0, 1.0]),
    ])

    query_embedding = [0.9, 0.1]

    with patch(
        "agent_fabric.infrastructure.workspace.run_index.embed_text",
        new_callable=AsyncMock,
        return_value=query_embedding,
    ):
        result = await semantic_search_index(
            workspace, "any query", "nomic-embed-text", "http://localhost:11434", top_k=2
        )

    assert len(result) == 2
    assert result[0].run_id == "1"   # higher cosine sim to [0.9, 0.1]
    assert result[1].run_id == "2"


@pytest.mark.asyncio
async def test_semantic_search_respects_top_k(tmp_path: Path):
    """top_k limits the number of results returned."""
    entries = [
        _make_entry(str(i), f"task {i}", f"summary {i}", embedding=[float(i), 0.0])
        for i in range(1, 6)
    ]
    workspace = _write_index(tmp_path, entries)

    with patch(
        "agent_fabric.infrastructure.workspace.run_index.embed_text",
        new_callable=AsyncMock,
        return_value=[1.0, 0.0],
    ):
        result = await semantic_search_index(
            workspace, "query", "nomic-embed-text", "http://localhost:11434", top_k=3
        )

    assert len(result) == 3


# ---------------------------------------------------------------------------
# RunIndexConfig schema
# ---------------------------------------------------------------------------


def test_run_index_config_defaults():
    cfg = RunIndexConfig()
    assert cfg.embedding_model is None
    assert cfg.embedding_base_url is None


def test_run_index_config_with_model():
    cfg = RunIndexConfig(embedding_model="nomic-embed-text")
    assert cfg.embedding_model == "nomic-embed-text"
    assert cfg.embedding_base_url is None


def test_fabric_config_has_run_index():
    from agent_fabric.config.schema import FabricConfig, ModelConfig, SpecialistConfig

    fc = FabricConfig(
        models={"fast": ModelConfig(base_url="http://localhost:11434/v1", model="qwen2.5:7b")},
        specialists={
            "engineering": SpecialistConfig(
                description="eng",
                workflow="engineering",
                capabilities=["code_execution"],
            ),
        },
    )
    assert fc.run_index is not None
    assert fc.run_index.embedding_model is None
