"""
Failure service — A5 business logic: SFC prompt building + diagnosis parsing.
Implements the 12-code Step Failure Cascade (first-match-wins).
"""

import json
import logging
import re

from pydantic import ValidationError

from schemas import ExecutionResult, FailureDiagnosis

logger = logging.getLogger(__name__)


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


# SFC code registry — order matters (first-match-wins)
SFC_CODES = [
    "TASK_INPUT_INVALID",
    "TOOL_UNAVAILABLE",
    "TOOL_SELECTION_WRONG",
    "PARAMETER_HALLUCINATED",
    "TOOL_RESULT_MISINTERPRETED",
    "REASONING_INCOHERENT",
    "GOAL_DRIFT",
    "SCOPE_CREEP",
    "INFINITE_LOOP",
    "IRREVERSIBLE_UNGATED",
    "CONTEXT_OVERFLOW",
    "SUBAGENT_FAILURE",
    "PASS",
]


def build_prompt(template: str, result: ExecutionResult) -> str:
    """Fill prompt template with failed execution result data."""
    steps_text = "\n".join(
        f"{sr.step_number}. {sr.action} → {sr.status}" for sr in result.step_results
    )
    return (
        template.replace("{test_case_id}", result.test_case_id)
        .replace("{status}", result.status)
        .replace("{error_message}", result.error_message or "No error message")
        .replace("{steps}", steps_text)
        .replace("{retry_count}", str(result.retry_count))
    )


def parse_response(raw_text: str, test_case_id: str) -> FailureDiagnosis:
    """Parse LLM JSON → FailureDiagnosis. Returns TASK_INPUT_INVALID on failure."""
    try:
        data = json.loads(_strip_fences(raw_text))
        return FailureDiagnosis(**data)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        logger.error(
            "A5 parse failed", extra={"error": str(exc), "raw_preview": raw_text[:200]}
        )
        return FailureDiagnosis(
            test_case_id=test_case_id,
            sfc_code="TASK_INPUT_INVALID",
            sfc_number=0,
            root_cause="Could not parse failure diagnosis from LLM",
            fix_direction="Provide complete and well-formed test case input",
            confidence=0.0,
        )


def is_valid_sfc_code(code: str) -> bool:
    return code in SFC_CODES
