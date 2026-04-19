"""
A9 Memory Keeper — sole writer to all persistent memory.
Two methods only: write() persists a record; query() retrieves records.
No LLM. No business logic. Delegates all I/O to memory/db.py and memory/vector_store.py.

WRITE ACCESS RULE: Only this agent may call write functions in memory/.
All other agents call A9.write() — never import memory/db.py or memory/vector_store.py directly.
"""

import logging
import uuid
from pathlib import Path
from typing import Optional

from memory import db, vector_store
from schemas import MemoryQuery, MemoryResult, MemoryWrite

logger = logging.getLogger(__name__)


class A9MemoryKeeper:
    """
    Sole guardian of persistent memory for the QA Office pipeline.

    write(MemoryWrite) → MemoryResult
      Dispatches to the correct storage backend based on record_type:
        "run"            → SQLite run_history
        "selector"       → SQLite selector_stability
        "human_decision" → SQLite human_decisions
        "insight"        → SQLite reflection_insights
        "narrative"      → ChromaDB failure_narratives
        "domain"         → ChromaDB domain_knowledge

    query(MemoryQuery) → MemoryResult
      Dispatches based on query_type:
        "run_history"       → SQLite run_history
        "selector"          → SQLite selector_stability
        "human_decisions"   → SQLite human_decisions
        "insights"          → SQLite reflection_insights
        "similar_failures"  → ChromaDB semantic search
        "domain"            → ChromaDB domain_knowledge
        "pom_cache"         → SQLite pom_cache (by page_url)
        "pom_elements"      → ChromaDB semantic search over page elements
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path
        db.init_db(db_path)

    def write(self, record: MemoryWrite) -> MemoryResult:
        run_id = record.run_id or uuid.uuid4().hex[:8]
        logger.info(
            "A9 write",
            extra={
                "source_agent": record.source_agent,
                "record_type": record.record_type,
                "run_id": run_id,
                "test_case_id": record.test_case_id,
            },
        )
        try:
            return self._dispatch_write(record, run_id)
        except Exception as exc:
            logger.error("A9 write error: %s", exc, extra={"run_id": run_id})
            return MemoryResult(success=False, error_message=str(exc))

    def query(self, request: MemoryQuery) -> MemoryResult:
        logger.info("A9 query", extra={"query_type": request.query_type})
        try:
            return self._dispatch_query(request)
        except Exception as exc:
            logger.error("A9 query error: %s", exc)
            return MemoryResult(success=False, error_message=str(exc))

    # ── write dispatch ──────────────────────────────────────────────────────────

    def _dispatch_write(self, record: MemoryWrite, run_id: str) -> MemoryResult:
        p = record.payload
        rtype = record.record_type

        if rtype == "run":
            db.insert_run(
                run_id=run_id,
                test_case_id=record.test_case_id,
                module=record.module,
                status=p["status"],
                root_cause=p.get("root_cause"),
                confidence=p.get("confidence"),
                retry_count=p.get("retry_count", 0),
                duration_ms=p.get("duration_ms", 0),
                db_path=self._db_path,
            )
        elif rtype == "selector":
            db.upsert_selector(
                selector_value=p["selector_value"],
                strategy=p["strategy"],
                test_case_id=record.test_case_id,
                passed=p["passed"],
                db_path=self._db_path,
            )
        elif rtype == "human_decision":
            db.insert_human_decision(
                run_id=run_id,
                test_case_id=record.test_case_id,
                decision=p["decision"],
                reason=p.get("reason"),
                decided_by=p.get("decided_by", "human"),
                db_path=self._db_path,
            )
        elif rtype == "insight":
            db.insert_insight(
                agent_id=record.source_agent,
                insight_text=p["insight_text"],
                run_count=p.get("run_count", 1),
                expires_at=p.get("expires_at"),
                db_path=self._db_path,
            )
        elif rtype == "narrative":
            vector_store.add_failure_narrative(
                doc_id=p.get("doc_id", f"{run_id}_{record.test_case_id}"),
                text=p["text"],
                metadata=p.get("metadata", {}),
            )
        elif rtype == "domain":
            vector_store.add_domain_knowledge(
                doc_id=p["doc_id"],
                text=p["text"],
                metadata=p.get("metadata", {}),
            )
        elif rtype == "pom_cache":
            db.upsert_pom_cache(
                page_url=p["page_url"],
                page_name=p["page_name"],
                class_name=p["class_name"],
                elements_json=p["elements_json"],
                ttl_days=p.get("ttl_days", 7),
                db_path=self._db_path,
            )
        elif rtype == "pom_element":
            vector_store.add_pom_element(
                doc_id=p["doc_id"],
                text=p["text"],
                metadata=p.get("metadata", {}),
            )
        else:
            return MemoryResult(
                success=False,
                error_message=f"Unknown record_type: {rtype}",
            )

        return MemoryResult(success=True)

    # ── query dispatch ──────────────────────────────────────────────────────────

    def _dispatch_query(self, request: MemoryQuery) -> MemoryResult:
        qtype = request.query_type

        if qtype == "run_history":
            rows = db.get_run_history(
                request.test_case_id, limit=request.limit, db_path=self._db_path
            )
            return MemoryResult(success=True, records=rows)

        if qtype == "selector":
            row = db.get_selector_stability(
                request.selector_value, db_path=self._db_path
            )
            return MemoryResult(success=True, records=[row] if row else [])

        if qtype == "human_decisions":
            rows = db.get_human_decisions(request.test_case_id, db_path=self._db_path)
            return MemoryResult(success=True, records=rows)

        if qtype == "insights":
            rows = db.get_insights(request.agent_id, db_path=self._db_path)
            return MemoryResult(success=True, records=rows)

        if qtype == "similar_failures":
            hits = vector_store.query_similar_failures(
                request.text, n_results=request.limit
            )
            return MemoryResult(success=True, records=hits)

        if qtype == "domain":
            hits = vector_store.query_domain_knowledge(
                request.text, n_results=request.limit
            )
            return MemoryResult(success=True, records=hits)

        if qtype == "pom_cache":
            # request.text is the page_url
            row = db.get_pom_cache(request.text, db_path=self._db_path)
            return MemoryResult(success=True, records=[row] if row else [])

        if qtype == "pom_elements":
            hits = vector_store.query_pom_elements(
                request.text, n_results=request.limit
            )
            return MemoryResult(success=True, records=hits)

        return MemoryResult(
            success=False,
            error_message=f"Unknown query_type: {qtype}",
        )
