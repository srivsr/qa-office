"""
Vector Store — ChromaDB adapter for A9 Memory Keeper.
Two collections:
  failure_narratives — semantic search over failure descriptions
  domain_knowledge   — application module knowledge, test patterns
WRITE ACCESS: Only A9 Memory Keeper may call add_* functions here.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_CHROMA_DIR = Path(__file__).parent / "chroma_db"
_FAILURE_COLLECTION = "failure_narratives"
_DOMAIN_COLLECTION = "domain_knowledge"
_POM_COLLECTION = "pom_elements"


def _get_client():
    import chromadb

    return chromadb.PersistentClient(path=str(_CHROMA_DIR))


def _get_collection(name: str):
    return _get_client().get_or_create_collection(name)


# ── failure_narratives ─────────────────────────────────────────────────────────


def add_failure_narrative(
    doc_id: str,
    text: str,
    metadata: Optional[Dict] = None,
) -> None:
    col = _get_collection(_FAILURE_COLLECTION)
    col.upsert(
        ids=[doc_id],
        documents=[text],
        metadatas=[metadata or {}],
    )
    logger.debug("vector_store: upserted failure narrative %s", doc_id)


def query_similar_failures(
    text: str,
    n_results: int = 5,
) -> List[Dict]:
    col = _get_collection(_FAILURE_COLLECTION)
    try:
        res = col.query(query_texts=[text], n_results=n_results)
    except Exception as exc:
        logger.warning("vector_store: query_similar_failures failed: %s", exc)
        return []
    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    return [{"id": i, "text": d, "metadata": m} for i, d, m in zip(ids, docs, metas)]


# ── domain_knowledge ───────────────────────────────────────────────────────────


def add_domain_knowledge(
    doc_id: str,
    text: str,
    metadata: Optional[Dict] = None,
) -> None:
    col = _get_collection(_DOMAIN_COLLECTION)
    col.upsert(
        ids=[doc_id],
        documents=[text],
        metadatas=[metadata or {}],
    )
    logger.debug("vector_store: upserted domain knowledge %s", doc_id)


def query_domain_knowledge(
    text: str,
    n_results: int = 5,
) -> List[Dict]:
    col = _get_collection(_DOMAIN_COLLECTION)
    try:
        res = col.query(query_texts=[text], n_results=n_results)
    except Exception as exc:
        logger.warning("vector_store: query_domain_knowledge failed: %s", exc)
        return []
    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    return [{"id": i, "text": d, "metadata": m} for i, d, m in zip(ids, docs, metas)]


# ── pom_elements ───────────────────────────────────────────────────────────────


def add_pom_element(
    doc_id: str,
    text: str,
    metadata: Optional[Dict] = None,
) -> None:
    col = _get_collection(_POM_COLLECTION)
    col.upsert(
        ids=[doc_id],
        documents=[text],
        metadatas=[metadata or {}],
    )
    logger.debug("vector_store: upserted pom element %s", doc_id)


def query_pom_elements(
    text: str,
    n_results: int = 5,
) -> List[Dict]:
    col = _get_collection(_POM_COLLECTION)
    try:
        res = col.query(query_texts=[text], n_results=n_results)
    except Exception as exc:
        logger.warning("vector_store: query_pom_elements failed: %s", exc)
        return []
    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    return [{"id": i, "text": d, "metadata": m} for i, d, m in zip(ids, docs, metas)]
