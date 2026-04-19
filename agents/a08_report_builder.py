"""
A8 Report Builder — thin orchestrator.
One job: list[TestCase] + list[ExecutionResult] → AgentResult(artifacts={"report": RunReport}).
All report writing logic lives in tools/report_writer.py.
"""

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from schemas import (
    AgentResult,
    ExecutionResult,
    HealthStatus,
    SeedResult,
    TestCase,
)
from tools.report_writer import ReportWriter, _build_compliance

logger = logging.getLogger(__name__)


class A8ReportBuilder:
    """
    Produces HTML + Excel reports (FR5 — leadership-quality).

    Input:  list[TestCase], list[ExecutionResult], run metadata
    Output: AgentResult
              status="success"|"error"
              artifacts={"report": RunReport}
              metrics={"duration_ms": int}

    Failure modes:
    - Output dir not writable → AgentResult(status="error")
    - ExcelReporter unavailable → HTML still written, logged warning
    """

    def __init__(self) -> None:
        self._writer = ReportWriter()

    def run(
        self,
        test_cases: List[TestCase],
        results: List[ExecutionResult],
        run_id: Optional[str] = None,
        app_url: str = "",
        output_dir: str = "runs",
        app_name: str = "",
        started_at: Optional[datetime] = None,
        health_status: Optional[HealthStatus] = None,
        seed_result: Optional[SeedResult] = None,
    ) -> AgentResult:
        """
        Build HTML + Excel reports and return AgentResult.

        Args:
            test_cases:  From A1 (defines display order)
            results:     From A4 (keyed by test_case_id inside writer)
            run_id:      Trace ID from orchestrator
            output_dir:  Directory for report files
            app_name:    Display name in report header
            started_at:  Run start time (defaults to now)
        """
        run_id = run_id or uuid.uuid4().hex[:8]
        started_at = started_at or datetime.now(timezone.utc)
        logger.info("A8 start", extra={"run_id": run_id, "agent": "A8ReportBuilder"})
        t0 = time.time()

        env_health = health_status.status if health_status else None
        seed_summary = (
            f"{seed_result.recipes_applied} recipes, {len(seed_result.modules)} modules"
            if seed_result and seed_result.seeded
            else None
        )
        compliance = _build_compliance(
            run_id,
            started_at,
            test_cases,
            env_health=env_health,
            seed_summary=seed_summary,
        )
        try:
            report = self._writer.write(
                test_cases,
                results,
                run_id,
                app_name,
                str(output_dir),
                started_at,
                compliance=compliance,
            )
        except OSError as exc:
            logger.error("A8 report write failed: %s", exc, extra={"run_id": run_id})
            return AgentResult(status="error", confidence=1.0, error_message=str(exc))

        ms = int((time.time() - t0) * 1000)
        logger.info(
            "A8 complete",
            extra={"run_id": run_id, "pass_rate": report.pass_rate, "duration_ms": ms},
        )
        return AgentResult(
            status="success",
            confidence=1.0,
            artifacts={"report": report},
            metrics={"duration_ms": ms},
        )
