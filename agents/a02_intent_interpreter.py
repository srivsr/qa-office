"""
A2 Intent Interpreter — thin orchestrator.
One job: TestCase → AgentResult(artifacts={"intent": ExecutableIntent}).
Uses claude-sonnet-4-6. Implements ACT/REVIEW/PAUSE gating.
All logic in services/intent_service.py. Prompt in prompts/a02_intent_v1.txt.
"""

import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from config.settings import settings as default_settings
from schemas import AgentDecision, AgentResult, TestCase
from services import confidence_service, intent_service
from tools.llm_client import LLMClient

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parents[1] / "prompts"


class A2IntentInterpreter:
    """
    Converts raw TestCase steps into typed ExecutableIntent using LLM.

    Confidence gating (CODING_STANDARDS §15):
    - ACT    (≥0.85) → status="success", proceed automatically
    - REVIEW (0.60–0.85) → status="review", review_required=True
    - PAUSE  (<0.60) → status="pause", stops downstream pipeline

    Input:  TestCase (from A1)
    Output: AgentResult
              artifacts={"intent": ExecutableIntent.model_dump()}
              metrics={"duration_ms", "prompt_version", "input_tokens", "output_tokens"}

    Failure modes:
    - LLM API error   → AgentResult(status="error", retryable=True)
    - Parse failure   → AgentResult(status="pause", confidence=0.0)
    """

    def __init__(self, settings=None) -> None:
        self._settings = settings or default_settings
        self._llm = LLMClient(model=self._settings.a2_model, settings=self._settings)
        self.prompt_template = (_PROMPTS_DIR / "a02_intent_v1.txt").read_text(encoding="utf-8")
        self.persona_template = (_PROMPTS_DIR / "a02_persona_v1.txt").read_text(encoding="utf-8")
        self.prompt_version = "a02_intent_v1"

    def run(self, test_case: TestCase, run_id: Optional[str] = None, app_name: str = "") -> AgentResult:
        run_id = run_id or uuid.uuid4().hex[:8]
        logger.info(
            "A2 start",
            extra={
                "run_id": run_id,
                "agent": "A2IntentInterpreter",
                "test_case_id": test_case.id,
            },
        )
        t0 = time.time()

        persona_ctx = intent_service.get_persona_context(
            test_case.persona or "default", self.persona_template, app_context=app_name
        )
        try:
            raw = self._llm.complete(
                intent_service.build_prompt(
                    self.prompt_template, test_case, persona_ctx
                ),
                max_tokens=self._settings.a2_max_tokens,
                run_id=run_id,
                prompt_version=self.prompt_version,
            )
        except Exception as exc:
            logger.error("A2 LLM error: %s", exc, extra={"run_id": run_id})
            return AgentResult(
                status="error", confidence=0.0, error_message=str(exc), retryable=True
            )

        intent = intent_service.parse_response(raw, test_case.id)
        decision = confidence_service.get_decision(intent.confidence, self._settings)
        ms = int((time.time() - t0) * 1000)

        logger.info(
            "A2 complete",
            extra={
                "run_id": run_id,
                "decision": decision,
                "confidence": intent.confidence,
                "duration_ms": ms,
            },
        )

        if decision == AgentDecision.PAUSE:
            logger.warning(
                "A2 PAUSE — escalating to A7",
                extra={"run_id": run_id, "confidence": intent.confidence},
            )
            return AgentResult(
                status="pause",
                confidence=intent.confidence,
                review_required=True,
                error_message=f"Confidence {intent.confidence:.2f} below threshold. Ambiguities: {intent.ambiguities}",
                artifacts={"intent": intent.model_dump()},
                metrics={"duration_ms": ms, "prompt_version": self.prompt_version},
            )

        return AgentResult(
            status="review" if decision == AgentDecision.REVIEW else "success",
            confidence=intent.confidence,
            review_required=(decision == AgentDecision.REVIEW),
            artifacts={"intent": intent.model_dump()},
            metrics={"duration_ms": ms, "prompt_version": self.prompt_version},
        )
