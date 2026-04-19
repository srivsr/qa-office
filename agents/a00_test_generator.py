"""
A0 Test Generator — thin orchestrator.
One job: plain-English requirement → AgentResult(artifacts={"test_cases": [...]}).
Uses claude-sonnet-4-6. Implements ACT/REVIEW/PAUSE gating.
Output type is identical to A1 Ingestion — feeds the same A2→…→A8 pipeline.
All logic in services/generator_service.py. Prompt in prompts/a00_generator_v1.txt.
"""

import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from config.settings import settings as default_settings
from schemas import AgentResult
from services import confidence_service, generator_service
from tools.llm_client import LLMClient

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parents[1] / "prompts"


class A0TestGenerator:
    """
    Generates TestCase objects from a plain-English requirement description.

    Input:  requirement: str, optional module/priority/count
    Output: AgentResult
              artifacts={"test_cases": list[TestCase], "coverage_note": str}

    Confidence gating:
    - ACT    (≥0.85) → return generated cases
    - REVIEW (0.60–0.85) → return cases, flag for human review
    - PAUSE  (<0.60) → do not use cases, escalate to A7

    Use when:
    - BlueTree has not provided existing test cases
    - Rapid coverage expansion from new requirements
    """

    def __init__(self, settings=None) -> None:
        self._settings = settings or default_settings
        self._llm = LLMClient(model=self._settings.a2_model, settings=self._settings)
        self.prompt_template = (_PROMPTS_DIR / "a00_generator_v1.txt").read_text(encoding="utf-8")
        self.prompt_version = "a00_generator_v1"

    def run(
        self,
        requirement: str,
        module: str = "General",
        priority: str = "Medium",
        count: int = 4,
        run_id: Optional[str] = None,
        app_url: str = "",
        app_name: str = "",
    ) -> AgentResult:
        run_id = run_id or uuid.uuid4().hex[:8]
        logger.info(
            "A0 start",
            extra={
                "run_id": run_id,
                "agent": "A0TestGenerator",
                "module": module,
                "count": count,
            },
        )
        t0 = time.time()

        try:
            raw = self._llm.complete(
                generator_service.build_prompt(
                    self.prompt_template, requirement, module, priority, count,
                    app_url=app_url, app_name=app_name,
                ),
                max_tokens=self._settings.a0_max_tokens,
                run_id=run_id,
                prompt_version=self.prompt_version,
                timeout=self._settings.a0_llm_timeout_s,
            )
        except Exception as exc:
            logger.error("A0 LLM error: %s", exc, extra={"run_id": run_id})
            return AgentResult(
                status="error", confidence=0.0, error_message=str(exc), retryable=True
            )

        output = generator_service.parse_response(raw, module)
        decision = confidence_service.get_decision(output.confidence, self._settings)
        ms = int((time.time() - t0) * 1000)

        logger.info(
            "A0 complete",
            extra={
                "run_id": run_id,
                "decision": decision,
                "confidence": output.confidence,
                "generated": len(output.test_cases),
                "duration_ms": ms,
            },
        )

        if decision.value == "pause":
            logger.warning(
                "A0 PAUSE — low-confidence generation",
                extra={"run_id": run_id, "coverage_note": output.coverage_note},
            )
            return AgentResult(
                status="pause",
                confidence=output.confidence,
                review_required=True,
                error_message=(
                    f"Generation confidence {output.confidence:.2f} too low — "
                    f"requirement may be too ambiguous. {output.coverage_note}"
                ),
                artifacts={
                    "test_cases": generator_service.to_test_cases(output),
                    "coverage_note": output.coverage_note,
                },
                metrics={"duration_ms": ms, "prompt_version": self.prompt_version},
            )

        test_cases = generator_service.to_test_cases(output)
        return AgentResult(
            status="review" if decision.value == "review" else "success",
            confidence=output.confidence,
            review_required=(decision.value == "review"),
            artifacts={"test_cases": test_cases, "coverage_note": output.coverage_note},
            metrics={
                "duration_ms": ms,
                "prompt_version": self.prompt_version,
                "generated": len(test_cases),
            },
        )
