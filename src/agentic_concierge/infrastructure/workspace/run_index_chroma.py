"""ChromaDB-backed run index — P11-6.

Requires the ``[embed]`` extra: ``pip install 'agentic-concierge[embed]'``
which pulls in ``chromadb``.  This module uses lazy imports so it can be
imported freely regardless of whether the extra is installed.

Usage::

    idx = ChromaRunIndex("/path/to/chromadb", "agentic_concierge_runs")
    idx.add(entry, embedding_vector)
    results = idx.search(query_embedding, top_k=10)
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from agentic_concierge.infrastructure.workspace.run_index import RunIndexEntry

logger = logging.getLogger(__name__)


def is_available() -> bool:
    """Return ``True`` if the ``chromadb`` package is importable."""
    import importlib.util
    return importlib.util.find_spec("chromadb") is not None


class ChromaRunIndex:
    """ChromaDB persistent collection backing the run index.

    The collection stores one document per run with the embedding vector and
    all ``RunIndexEntry`` fields serialised as ChromaDB metadata.  Cosine
    similarity is selected at collection-creation time (``hnsw:space=cosine``).

    Args:
        path: Directory path for ChromaDB persistent storage.
        collection_name: ChromaDB collection name.

    Raises:
        ImportError: If ``chromadb`` is not installed.
    """

    def __init__(
        self,
        path: str,
        collection_name: str = "agentic_concierge_runs",
    ) -> None:
        import chromadb  # type: ignore[import]  # lazy — guarded by [embed] extra

        self._client = chromadb.PersistentClient(path=path)
        self._collection: Any = self._client.get_or_create_collection(
            collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.debug(
            "ChromaRunIndex: opened collection %r at %s (count=%d)",
            collection_name, path, self._collection.count(),
        )

    def add(self, entry: RunIndexEntry, embedding: List[float]) -> None:
        """Upsert *entry* with its *embedding* into the collection.

        Uses upsert so re-running the same ``run_id`` updates the record
        rather than duplicating it.

        Args:
            entry: ``RunIndexEntry`` to store.
            embedding: Pre-computed embedding vector.
        """
        metadata = {
            "run_id": entry.run_id,
            "timestamp": entry.timestamp,
            "specialist_ids": ",".join(entry.specialist_ids),
            "prompt_prefix": entry.prompt_prefix[:500],   # ChromaDB metadata limit
            "summary": entry.summary[:500],
            "workspace_path": entry.workspace_path,
            "run_dir": entry.run_dir,
            "routing_method": entry.routing_method,
            "model_name": entry.model_name,
        }
        self._collection.upsert(
            ids=[entry.run_id],
            embeddings=[embedding],
            metadatas=[metadata],
        )
        logger.debug("ChromaRunIndex: upserted run %s", entry.run_id)

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 10,
    ) -> List[RunIndexEntry]:
        """Return the top-k entries closest to *query_embedding*.

        Returns an empty list when the collection is empty.

        Args:
            query_embedding: Query vector (same dimensionality as stored vectors).
            top_k: Maximum number of results.

        Returns:
            List of ``RunIndexEntry`` sorted by descending cosine similarity.
        """
        count = self._collection.count()
        if count == 0:
            return []

        n_results = min(top_k, count)
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
        )
        metadatas: List[dict] = results["metadatas"][0]
        return [_meta_to_entry(m) for m in metadatas]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _meta_to_entry(meta: dict) -> RunIndexEntry:
    """Reconstruct a ``RunIndexEntry`` from ChromaDB metadata."""
    raw_ids = meta.get("specialist_ids", "")
    specialist_ids = [s for s in raw_ids.split(",") if s] if raw_ids else []

    return RunIndexEntry(
        run_id=str(meta.get("run_id", "")),
        timestamp=float(meta.get("timestamp", 0.0)),
        specialist_ids=specialist_ids,
        prompt_prefix=str(meta.get("prompt_prefix", "")),
        summary=str(meta.get("summary", "")),
        workspace_path=str(meta.get("workspace_path", "")),
        run_dir=str(meta.get("run_dir", "")),
        routing_method=str(meta.get("routing_method", "")),
        model_name=str(meta.get("model_name", "")),
        # Embeddings are not round-tripped through ChromaDB metadata (they are
        # stored as the vector itself — retrieving them is not needed for search).
        embedding=None,
    )
