"""
A6 Self-Healer — thin orchestrator.
One job: FailureDiagnosis → AgentResult(artifacts={"heal": HealResult}).
Uses claude-sonnet-4-6. Implements ACT/REVIEW/PAUSE gating.
Only heals TOOL_SELECTION_WRONG. Always logs every repair (FR4).
All logic in services/healer_service.py. Prompt in prompts/a06_healer_v1.txt.
"""

import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from agents.a09_memory_keeper import A9MemoryKeeper
from config.settings import settings as default_settings
from schemas import AgentDecision, AgentResult, FailureDiagnosis, MemoryWrite
from services import confidence_service, healer_service
from tools.llm_client import LLMClient

logger = logging.getLogger(__name__)
_memory = A9MemoryKeeper()
_PROMPTS_DIR = Path(__file__).parents[1] / "prompts"


class A6SelfHealer:
    """
    Auto-repairs broken locators when confidence permits (FR4).

    Confidence gating (CODING_STANDARDS §15):
    - ACT    (≥0.85) → auto-apply repair
    - REVIEW (0.60–0.85) → apply but flag for human (always REVIEW for repairs per §15)
    - PAUSE  (<0.60) → escalate to A7, do not apply

    Note: Per CODING_STANDARDS §15, any self-heal repair applied always requires REVIEW
    regardless of confidence. This overrides ACT status for this agent.

    Input:  FailureDiagnosis (from A5), broken_selector: str
    Output: AgentResult
              artifacts={"heal": HealResult.model_dump()}
    """

    def __init__(self, settings=None) -> None:
        self._settings = settings or default_settings
        self._llm = LLMClient(model=self._settings.a6_model, settings=self._settings)
        self.prompt_template = (_PROMPTS_DIR / "a06_healer_v1.txt").read_text(encoding="utf-8")
        self.prompt_version = "a06_healer_v1"

    def run(
        self,
        diagnosis: FailureDiagnosis,
        broken_selector: str,
        run_id: Optional[str] = None,
    ) -> AgentResult:
        run_id = run_id or uuid.uuid4().hex[:8]
        logger.info(
            "A6 start",
            extra={
                "run_id": run_id,
                "agent": "A6SelfHealer",
                "test_case_id": diagnosis.test_case_id,
                "sfc_code": diagnosis.sfc_code,
            },
        )
        t0 = time.time()

        if not healer_service.can_heal(diagnosis):
            logger.info(
                "A6 skip — not healable SFC code %s",
                diagnosis.sfc_code,
                extra={"run_id": run_id},
            )
            return AgentResult(
                status="success",
                confidence=1.0,
                error_message=f"SFC code {diagnosis.sfc_code} is not healable by A6",
                artifacts={"heal": None},
            )

        try:
            raw = self._llm.complete(
                healer_service.build_prompt(
                    self.prompt_template, diagnosis, broken_selector
                ),
                max_tokens=self._settings.a6_max_tokens,
                run_id=run_id,
                prompt_version=self.prompt_version,
            )
        except Exception as exc:
            logger.error("A6 LLM error: %s", exc, extra={"run_id": run_id})
            return AgentResult(
                status="error", confidence=0.0, error_message=str(exc), retryable=True
            )

        heal = healer_service.parse_response(
            raw, diagnosis.test_case_id, broken_selector
        )
        decision = confidence_service.get_decision(heal.confidence, self._settings)
        ms = int((time.time() - t0) * 1000)

        logger.info(
            "A6 complete",
            extra={
                "run_id": run_id,
                "decision": decision,
                "confidence": heal.confidence,
                "duration_ms": ms,
            },
        )

        if decision == AgentDecision.PAUSE:
            logger.warning("A6 PAUSE — low confidence repair", extra={"run_id": run_id})
            return AgentResult(
                status="pause",
                confidence=heal.confidence,
                review_required=True,
                error_message=f"Repair confidence {heal.confidence:.2f} too low — escalating to A7",
                artifacts={"heal": heal.model_dump()},
                metrics={"duration_ms": ms, "prompt_version": self.prompt_version},
            )

        _memory.write(
            MemoryWrite(
                source_agent="A6",
                record_type="selector",
                run_id=run_id,
                test_case_id=diagnosis.test_case_id,
                payload={
                    "selector_value": heal.fixed_selector,
                    "strategy": heal.strategy,
                    "passed": decision != AgentDecision.PAUSE,
                },
            )
        )

        # Per CODING_STANDARDS §15 — any applied repair always requires human REVIEW
        return AgentResult(
            status="review",
            confidence=heal.confidence,
            review_required=True,  # always true for self-heal repairs
            artifacts={"heal": heal.model_dump()},
            metrics={"duration_ms": ms, "prompt_version": self.prompt_version},
        )
