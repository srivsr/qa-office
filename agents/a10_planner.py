"""
A10 Planner — strategic test ordering and post-run reflection.
One job (planning): RunRequest + TestCases → AgentResult(artifacts={"plan": TestPlan}).
Second method (reflection): TestPlan + Results → AgentResult(artifacts={"reflection": ReflectionInsight}).

ADR-016: plan() and reflect() are separate public methods — planning and reflection
are distinct lifecycle phases in the A11 mission flow.
"""

import logging
import time
from pathlib import Path
from typing import Any, List, Optional

from config.settings import settings as default_settings
from schemas import AgentResult, MemoryQuery, MemoryWrite, RunRequest, TestPlan
from services import planner_service
from tools.llm_client import LLMClient

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parents[1] / "prompts"


class A10Planner:
    """
    Prioritises test execution order by risk score, then calibrates
    risk weights by comparing predictions against actual failures.

    Injectable llm and memory for testing.
    """

    def __init__(
        self,
        settings=None,
        llm: Optional[Any] = None,
        memory: Optional[Any] = None,
    ) -> None:
        self._settings = settings or default_settings
        self._llm = llm or LLMClient(
            model=self._settings.a10_model, settings=self._settings
        )
        self._memory = memory
        self._plan_prompt = (_PROMPTS_DIR / "a10_planner_v1.txt").read_text(encoding="utf-8")
        self._reflect_prompt = (_PROMPTS_DIR / "a10_reflection_v1.txt").read_text(encoding="utf-8")
        self.prompt_version = "a10_planner_v1"

    def run(
        self,
        run_request: RunRequest,
        test_cases: List[Any],
        run_id: str = "unknown",
    ) -> AgentResult:
        """Plan: query A9 history → score risks → order test cases → return TestPlan."""
        t0 = time.time()
        logger.info("A10 plan start", extra={"run_id": run_id})

        history = self._fetch_history(test_cases, run_id)
        tc_ids = [tc.id for tc in test_cases]
        prompt = planner_service.build_plan_prompt(
            self._plan_prompt, run_request, tc_ids, history
        )

        try:
            raw = self._llm.complete(
                prompt,
                max_tokens=self._settings.a10_max_tokens,
                run_id=run_id,
                prompt_version=self.prompt_version,
            )
        except Exception as exc:
            logger.error("A10 LLM error: %s", exc, extra={"run_id": run_id})
            plan = TestPlan(run_id=run_id, ordered_test_case_ids=tc_ids, confidence=0.5)
            return AgentResult(
                status="success", confidence=0.5, artifacts={"plan": plan.model_dump()}
            )

        try:
            plan = planner_service.parse_plan_response(raw, test_cases, run_id)
        except Exception as exc:
            logger.error("A10 parse error: %s", exc, extra={"run_id": run_id})
            plan = TestPlan(run_id=run_id, ordered_test_case_ids=tc_ids, confidence=0.5)
            ms = int((time.time() - t0) * 1000)
            return AgentResult(
                status="success", confidence=0.5, artifacts={"plan": plan.model_dump()}
            )

        # parse_plan_response falls back internally — if confidence=0.5 from fallback, treat as success
        ms = int((time.time() - t0) * 1000)
        logger.info(
            "A10 plan complete",
            extra={"run_id": run_id, "confidence": plan.confidence, "duration_ms": ms},
        )

        if plan.confidence == 0.5 and not plan.risk_scores:
            # Parse fallback — graceful degradation, always success
            return AgentResult(
                status="success",
                confidence=0.5,
                artifacts={"plan": plan.model_dump()},
                metrics={"duration_ms": ms, "prompt_version": self.prompt_version},
            )

        status = (
            "success" if plan.confidence >= self._settings.act_threshold else "review"
        )
        return AgentResult(
            status=status,
            confidence=plan.confidence,
            review_required=(status == "review"),
            artifacts={"plan": plan.model_dump()},
            metrics={"duration_ms": ms, "prompt_version": self.prompt_version},
        )

    def reflect(
        self,
        plan: TestPlan,
        results: List[Any],
        run_id: str = "unknown",
    ) -> AgentResult:
        """Reflect: compare plan predictions vs actual failures → store insight in A9."""
        t0 = time.time()
        logger.info("A10 reflect start", extra={"run_id": run_id})

        prompt = planner_service.build_reflection_prompt(
            self._reflect_prompt, plan, results, run_id
        )

        try:
            raw = self._llm.complete(
                prompt,
                max_tokens=self._settings.a10_reflection_max_tokens,
                run_id=run_id,
                prompt_version="a10_reflection_v1",
            )
        except Exception as exc:
            logger.warning("A10 reflect LLM error (non-fatal): %s", exc)
            raw = "{}"

        insight = planner_service.parse_reflection(raw, plan, results, run_id)

        if self._memory:
            self._memory.write(
                MemoryWrite(
                    source_agent="A10",
                    record_type="reflection",
                    run_id=run_id,
                    test_case_id="ALL",
                    payload=insight.model_dump(),
                )
            )

        ms = int((time.time() - t0) * 1000)
        logger.info(
            "A10 reflect complete",
            extra={
                "run_id": run_id,
                "accuracy": insight.prediction_accuracy,
                "duration_ms": ms,
            },
        )
        return AgentResult(
            status="success",
            confidence=insight.prediction_accuracy,
            artifacts={"reflection": insight.model_dump()},
            metrics={"duration_ms": ms},
        )

    def _fetch_history(self, test_cases: List[Any], run_id: str) -> dict:
        """Query A9 for per-module history. Returns {module: [records]}."""
        if not self._memory:
            return {}
        history: dict = {}
        seen_modules = set()
        for tc in test_cases:
            if tc.module in seen_modules:
                continue
            seen_modules.add(tc.module)
            res = self._memory.query(
                MemoryQuery(query_type="run_history", test_case_id=tc.id, limit=10)
            )
            if res.success:
                history[tc.module] = res.records
        return history
