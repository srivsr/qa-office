"""
A5 Failure Analyst — thin orchestrator.
One job: ExecutionResult (failed) → AgentResult(artifacts={"diagnosis": FailureDiagnosis}).
Uses claude-opus-4-5 (deep diagnosis). Implements ACT/REVIEW/PAUSE gating.
Implements 12-code Step Failure Cascade (SFC). Never marks failed without root cause.
All logic in services/failure_service.py. Prompt in prompts/a05_failure_v1.txt.
"""

import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from agents.a09_memory_keeper import A9MemoryKeeper
from config.settings import settings as default_settings
from schemas import AgentDecision, AgentResult, ExecutionResult, MemoryWrite
from services import confidence_service, failure_service
from tools.llm_client import LLMClient

logger = logging.getLogger(__name__)
_memory = A9MemoryKeeper()
_PROMPTS_DIR = Path(__file__).parents[1] / "prompts"


class A5FailureAnalyst:
    """
    Diagnoses test failures using the 12-code Step Failure Cascade (FR3).
    Uses Opus for deep reasoning — only called on failures.

    Input:  ExecutionResult with status "failed" or "error"
    Output: AgentResult
              artifacts={"diagnosis": FailureDiagnosis.model_dump()}

    Failure modes:
    - LLM API error  → AgentResult(status="error", retryable=True)
    - Parse failure  → FailureDiagnosis with TASK_INPUT_INVALID, confidence=0.0
    - PASS returned for failure → overridden, confidence=0.0

    Note: Only called for failed/error results. A4 passes all results; orchestrator
    filters to failures before calling A5.
    """

    def __init__(self, settings=None) -> None:
        self._settings = settings or default_settings
        self._llm = LLMClient(model=self._settings.a5_model, settings=self._settings)
        self.prompt_template = (_PROMPTS_DIR / "a05_failure_v1.txt").read_text(encoding="utf-8")
        self.prompt_version = "a05_failure_v1"

    def run(self, result: ExecutionResult, run_id: Optional[str] = None) -> AgentResult:
        run_id = run_id or uuid.uuid4().hex[:8]
        logger.info(
            "A5 start",
            extra={
                "run_id": run_id,
                "agent": "A5FailureAnalyst",
                "test_case_id": result.test_case_id,
            },
        )
        t0 = time.time()

        try:
            raw = self._llm.complete(
                failure_service.build_prompt(self.prompt_template, result),
                max_tokens=self._settings.a5_max_tokens,
                run_id=run_id,
                prompt_version=self.prompt_version,
            )
        except Exception as exc:
            logger.error("A5 LLM error: %s", exc, extra={"run_id": run_id})
            return AgentResult(
                status="error", confidence=0.0, error_message=str(exc), retryable=True
            )

        diagnosis = failure_service.parse_response(raw, result.test_case_id)
        decision = confidence_service.get_decision(diagnosis.confidence, self._settings)
        ms = int((time.time() - t0) * 1000)

        logger.info(
            "A5 complete",
            extra={
                "run_id": run_id,
                "sfc_code": diagnosis.sfc_code,
                "confidence": diagnosis.confidence,
                "duration_ms": ms,
            },
        )

        _memory.write(
            MemoryWrite(
                source_agent="A5",
                record_type="narrative",
                run_id=run_id,
                test_case_id=result.test_case_id,
                payload={
                    "text": f"{diagnosis.sfc_code}: {diagnosis.root_cause}",
                    "metadata": {
                        "sfc_code": diagnosis.sfc_code,
                        "confidence": diagnosis.confidence,
                        "run_id": run_id,
                    },
                },
            )
        )

        if decision == AgentDecision.PAUSE:
            logger.warning(
                "A5 PAUSE — low-confidence diagnosis", extra={"run_id": run_id}
            )
            return AgentResult(
                status="pause",
                confidence=diagnosis.confidence,
                review_required=True,
                error_message=f"Diagnosis confidence {diagnosis.confidence:.2f} too low",
                artifacts={"diagnosis": diagnosis.model_dump()},
                metrics={"duration_ms": ms, "prompt_version": self.prompt_version},
            )

        return AgentResult(
            status="review" if decision == AgentDecision.REVIEW else "success",
            confidence=diagnosis.confidence,
            review_required=(decision == AgentDecision.REVIEW),
            error_code=diagnosis.sfc_code,
            artifacts={"diagnosis": diagnosis.model_dump()},
            metrics={"duration_ms": ms, "prompt_version": self.prompt_version},
        )
