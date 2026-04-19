"""
A1 Ingestion — thin orchestrator.
One job: read BlueTree Excel → AgentResult(artifacts={"test_cases": [...]}).
All parsing logic lives in services/ingestion_service.py.
"""

import logging
import time
import uuid
from typing import Optional

from schemas import AgentResult
from services import ingestion_service
from services.ingestion_service import IngestionError

logger = logging.getLogger(__name__)


class A1Ingestion:
    """
    Reads BlueTree Excel test cases without modifying the source file (FR1).

    Input:  excel_path: str
    Output: AgentResult
              status="success", confidence=1.0
              artifacts={"test_cases": list[TestCase]}
              metrics={"total": int, "duration_ms": int}

    Failure modes:
    - File not found         → AgentResult(status="error")
    - Required columns absent → AgentResult(status="error", error_message=detail)
    """

    def run(self, excel_path: str, run_id: Optional[str] = None) -> AgentResult:
        """
        Parse BlueTree Excel → AgentResult.

        Args:
            excel_path: Path to BlueTree test case Excel file
            run_id:     Trace ID propagated from orchestrator

        Returns:
            AgentResult — never raises; errors surfaced in result envelope
        """
        run_id = run_id or uuid.uuid4().hex[:8]
        logger.info(
            "A1 start",
            extra={"run_id": run_id, "agent": "A1Ingestion", "file": excel_path},
        )
        t0 = time.time()

        try:
            test_cases = ingestion_service.parse(excel_path)
        except IngestionError as exc:
            logger.error("A1 ingestion error: %s", exc, extra={"run_id": run_id})
            return AgentResult(
                status="error",
                confidence=1.0,
                error_message=str(exc),
                retryable=False,
            )

        ms = int((time.time() - t0) * 1000)
        logger.info(
            "A1 complete",
            extra={"run_id": run_id, "total": len(test_cases), "duration_ms": ms},
        )
        return AgentResult(
            status="success",
            confidence=1.0,
            artifacts={"test_cases": test_cases},
            metrics={"total": len(test_cases), "duration_ms": ms},
        )
