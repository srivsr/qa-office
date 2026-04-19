"""
A3 Locator Scout — thin orchestrator.
One job: ExecutableIntent → AgentResult(artifacts={"selectors": SelectorResult}).
Uses claude-sonnet-4-6. Implements ACT/REVIEW/PAUSE gating.
Cache-first: queries A9 pom_elements before calling LLM (saves tokens + latency).
All logic in services/locator_service.py. Prompt in prompts/a03_locator_v1.txt.
"""

import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from config.settings import settings as default_settings
from schemas import AgentDecision, AgentResult, ExecutableIntent, MemoryQuery, SelectorResult, SelectorStep
from services import confidence_service, locator_service
from tools.llm_client import LLMClient

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parents[1] / "prompts"


class A3LocatorScout:
    """
    Finds stable Playwright selectors for every intent step.

    Selector priority enforced by prompt (CODING_STANDARDS §10):
    aria-label > data-testid > role+name > label > text > CSS > XPath

    Cache-first strategy:
    1. Query A9 pom_elements for each step (semantic search by action description)
    2. If all steps hit cache with stability="stable" → skip LLM, return cached selectors
    3. Cache miss → live LLM discovery → result written back to A9 by A14

    Input:  ExecutableIntent (from A2)
    Output: AgentResult
              artifacts={"selectors": SelectorResult.model_dump()}
              metrics={"cache_hit": bool, ...}

    Failure modes:
    - LLM API error  → AgentResult(status="error", retryable=True)
    - Parse failure  → AgentResult(status="pause", confidence=0.0)
    - No stable selectors → REVIEW or PAUSE depending on score
    """

    def __init__(self, settings=None, memory=None) -> None:
        self._settings = settings or default_settings
        self._llm = LLMClient(model=self._settings.a3_model, settings=self._settings)
        self.prompt_template = (_PROMPTS_DIR / "a03_locator_v1.txt").read_text(encoding="utf-8")
        self.prompt_version = "a03_locator_v1"
        self._memory = memory  # injected A9MemoryKeeper; lazy-loaded if None

    def run(
        self, intent: ExecutableIntent, run_id: Optional[str] = None, module: str = "General"
    ) -> AgentResult:
        run_id = run_id or uuid.uuid4().hex[:8]
        logger.info(
            "A3 start",
            extra={
                "run_id": run_id,
                "agent": "A3LocatorScout",
                "test_case_id": intent.test_case_id,
            },
        )
        t0 = time.time()

        # ── Cache-first: try A9 pom_elements ─────────────────────────────────
        cached_selectors = self._query_pom_cache(intent)
        if cached_selectors is not None:
            ms = int((time.time() - t0) * 1000)
            logger.info("A3 cache hit for %s", intent.test_case_id, extra={"run_id": run_id})
            decision = confidence_service.get_decision(
                cached_selectors.overall_confidence, self._settings
            )
            return AgentResult(
                status="review" if decision == AgentDecision.REVIEW else "success",
                confidence=cached_selectors.overall_confidence,
                review_required=(decision == AgentDecision.REVIEW),
                artifacts={"selectors": cached_selectors.model_dump()},
                metrics={"duration_ms": ms, "prompt_version": "pom_cache", "cache_hit": True},
            )

        # ── Live LLM discovery ────────────────────────────────────────────────
        try:
            raw = self._llm.complete(
                locator_service.build_prompt(self.prompt_template, intent, module=module),
                max_tokens=self._settings.a3_max_tokens,
                run_id=run_id,
                prompt_version=self.prompt_version,
            )
        except Exception as exc:
            logger.error("A3 LLM error: %s", exc, extra={"run_id": run_id})
            return AgentResult(
                status="error", confidence=0.0, error_message=str(exc), retryable=True
            )

        selectors = locator_service.parse_response(raw, intent.test_case_id)
        decision = confidence_service.get_decision(
            selectors.overall_confidence, self._settings
        )
        ms = int((time.time() - t0) * 1000)

        logger.info(
            "A3 complete",
            extra={
                "run_id": run_id,
                "decision": decision,
                "confidence": selectors.overall_confidence,
                "duration_ms": ms,
            },
        )

        if decision == AgentDecision.PAUSE:
            logger.warning(
                "A3 PAUSE — no stable selectors found", extra={"run_id": run_id}
            )
            return AgentResult(
                status="pause",
                confidence=selectors.overall_confidence,
                review_required=True,
                error_message=f"Selector confidence {selectors.overall_confidence:.2f} too low for autonomous execution",
                artifacts={"selectors": selectors.model_dump()},
                metrics={"duration_ms": ms, "prompt_version": self.prompt_version, "cache_hit": False},
            )

        return AgentResult(
            status="review" if decision == AgentDecision.REVIEW else "success",
            confidence=selectors.overall_confidence,
            review_required=(decision == AgentDecision.REVIEW),
            artifacts={"selectors": selectors.model_dump()},
            metrics={"duration_ms": ms, "prompt_version": self.prompt_version, "cache_hit": False},
        )

    # ── POM cache lookup ──────────────────────────────────────────────────────

    def _get_memory(self):
        if self._memory is None:
            from agents.a09_memory_keeper import A9MemoryKeeper
            self._memory = A9MemoryKeeper()
        return self._memory

    def _query_pom_cache(self, intent: ExecutableIntent) -> Optional[SelectorResult]:
        """
        Query A9 pom_elements for each step.
        Returns SelectorResult only if ALL steps find a stable cache hit.
        Returns None if any step misses (fall back to LLM).
        """
        try:
            memory = self._get_memory()
            step_results = []
            for step in intent.steps:
                query_text = f"{step.raw_action} {step.playwright_action}"
                result = memory.query(MemoryQuery(
                    query_type="pom_elements",
                    text=query_text,
                    limit=1,
                ))
                if not result.success or not result.records:
                    return None  # miss — use LLM
                hit = result.records[0]
                meta = hit.get("metadata", {})
                locator = meta.get("locator")
                if not locator or meta.get("stability") == "fragile":
                    return None  # fragile — use LLM
                step_results.append(SelectorStep(
                    step_number=step.step_number,
                    selector=locator,
                    strategy="pom_cache",
                    stability_score=0.90,
                    fallback_list=[],
                ))
            if not step_results:
                return None
            return SelectorResult(
                test_case_id=intent.test_case_id,
                selectors=step_results,
                overall_confidence=0.90,
            )
        except Exception as exc:
            logger.debug("A3 pom cache query error: %s", exc)
            return None
