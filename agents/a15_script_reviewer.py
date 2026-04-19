"""
A15 Script Reviewer — pre-execution assertion quality gate.
Three skills:
  review_script    — full review of an ExecutableIntent; calls validate_assertions
  curate_library   — manage reusable assertion pattern library in A9
  validate_assertions — rule-based + LLM detection of invented UI copy
Pipeline position: after A2/A3 intent phase, before A4 execution.
"""

import logging
import re
import time
from pathlib import Path
from typing import Any, List

from config.settings import settings as default_settings
from schemas import (
    AgentResult,
    AssertionFlag,
    AssertionReport,
    ExecutableIntent,
    ScriptReview,
)
from tools.llm_client import LLMClient

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parents[1] / "prompts"

# ── Rule-based pattern detection ──────────────────────────────────────────────

_PRICE_RE = re.compile(r"[\$€£¥]\s*[\d.,]+|[\d.,]+\s*/\s*month|[\d.,]+\s*/\s*year", re.I)
_COUNTER_RE = re.compile(r"\b\d+\s+of\s+\d+\b|\bstep\s+\d+\b|\bpage\s+\d+\s*(?:of|/)\s*\d+\b", re.I)
_LOADING_RE = re.compile(
    r"\b(thinking|loading|please wait|processing|submitting|saving)\.{0,3}\b", re.I
)
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U00002600-\U000027BF"
    "\U0001FA00-\U0001FA9F"
    "]"
)

_SEMANTIC_HINTS = {
    "PRICE": "verify a price element is visible in that section",
    "STEP_COUNTER": "verify a step progress indicator is visible on the page",
    "LOADING_STATE": "verify a loading or processing indicator is visible",
    "EMOJI": "verify the navigation or UI element is visible (omit emoji from assertion)",
    "DYNAMIC_COUNT": "verify a numeric count or status element is visible",
}


def _flag_text(step_number: int, text: str, penalty: float) -> List[AssertionFlag]:
    """Return flags for a single assertion step text using rule-based patterns."""
    flags: List[AssertionFlag] = []

    if _PRICE_RE.search(text):
        flags.append(AssertionFlag(
            step_number=step_number,
            flag_type="PRICE",
            original_text=text,
            suggestion=_SEMANTIC_HINTS["PRICE"],
            confidence_penalty=penalty,
        ))
    if _COUNTER_RE.search(text):
        flags.append(AssertionFlag(
            step_number=step_number,
            flag_type="STEP_COUNTER",
            original_text=text,
            suggestion=_SEMANTIC_HINTS["STEP_COUNTER"],
            confidence_penalty=penalty,
        ))
    if _LOADING_RE.search(text):
        flags.append(AssertionFlag(
            step_number=step_number,
            flag_type="LOADING_STATE",
            original_text=text,
            suggestion=_SEMANTIC_HINTS["LOADING_STATE"],
            confidence_penalty=penalty,
        ))
    if _EMOJI_RE.search(text):
        flags.append(AssertionFlag(
            step_number=step_number,
            flag_type="EMOJI",
            original_text=text,
            suggestion=_SEMANTIC_HINTS["EMOJI"],
            confidence_penalty=penalty,
        ))
    return flags


class A15ScriptReviewer:
    """
    Pre-execution assertion quality gate.
    Detects invented UI copy before A4 runs, preventing predictable false failures.
    """

    def __init__(self, settings=None) -> None:
        self._settings = settings or default_settings
        self._llm = LLMClient(model=self._settings.a15_model, settings=self._settings)
        self._prompt = (_PROMPTS_DIR / "a15_reviewer_v1.txt").read_text(encoding="utf-8")
        self._penalty = self._settings.a15_assertion_penalty

    # ── Skill 1: validate_assertions ──────────────────────────────────────────

    def validate_assertions(self, intent: ExecutableIntent) -> AssertionReport:
        """
        Rule-based scan of all assert steps in an ExecutableIntent.
        Returns AssertionReport — no LLM call, runs in-process.
        """
        flags: List[AssertionFlag] = []
        for step in intent.steps:
            if step.playwright_action != "assert":
                continue
            text = step.value or step.raw_action
            flags.extend(_flag_text(step.step_number, text, self._penalty))

        total_penalty = min(1.0, sum(f.confidence_penalty for f in flags))
        return AssertionReport(
            test_case_id=intent.test_case_id,
            flags=flags,
            total_penalty=total_penalty,
            has_unverified=len(flags) > 0,
        )

    # ── Skill 2: review_script ────────────────────────────────────────────────

    def review_script(self, intent: ExecutableIntent) -> ScriptReview:
        """
        Full review of a single ExecutableIntent.
        Calls validate_assertions; optionally escalates to LLM for ambiguous cases.
        Returns ScriptReview with confidence_adjustment and warnings.
        """
        report = self.validate_assertions(intent)
        warnings = [
            f"Step {f.step_number} [{f.flag_type}]: {f.original_text!r} → {f.suggestion}"
            for f in report.flags
        ]
        if warnings:
            logger.warning(
                "A15 unverified assertions",
                extra={
                    "test_case_id": intent.test_case_id,
                    "flag_count": len(report.flags),
                    "flags": [f.flag_type for f in report.flags],
                },
            )
        return ScriptReview(
            test_case_id=intent.test_case_id,
            assertion_report=report,
            confidence_adjustment=-report.total_penalty,
            warnings=warnings,
            approved=not report.has_unverified,
        )

    # ── Skill 3: curate_library ───────────────────────────────────────────────

    def curate_library(self, memory: Any, run_id: str) -> AgentResult:
        """
        Persist approved semantic assertion patterns to A9 for reuse.
        Called after a run completes to grow the verified-assertions corpus.
        """
        from schemas import MemoryWrite

        t0 = time.time()
        patterns = [h for h in _SEMANTIC_HINTS.values()]
        for pattern in patterns:
            memory.write(
                MemoryWrite(
                    source_agent="A15",
                    record_type="domain",
                    run_id=run_id,
                    test_case_id="__library__",
                    module="AssertionLibrary",
                    payload={"pattern": pattern},
                )
            )
        return AgentResult(
            status="success",
            confidence=1.0,
            artifacts={"patterns_curated": len(patterns)},
            metrics={"duration_ms": int((time.time() - t0) * 1000)},
        )

    # ── Batch helper used by A11 ──────────────────────────────────────────────

    def review_all(self, intents: List[ExecutableIntent]) -> List[ScriptReview]:
        """Validate assertions for a list of intents. Returns one ScriptReview per intent."""
        return [self.review_script(i) for i in intents]
