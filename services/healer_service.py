"""
Healer service — A6 business logic: repair prompt building + HealResult parsing.
Only heals TOOL_SELECTION_WRONG failures; everything else → confidence 0.0.
"""

import json
import logging
import re

from pydantic import ValidationError

from schemas import FailureDiagnosis, HealResult

logger = logging.getLogger(__name__)


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


HEALABLE_SFC_CODE = "TOOL_SELECTION_WRONG"


def build_prompt(
    template: str, diagnosis: FailureDiagnosis, broken_selector: str
) -> str:
    """Fill prompt template with diagnosis context for healing."""
    return (
        template.replace("{test_case_id}", diagnosis.test_case_id)
        .replace("{sfc_code}", diagnosis.sfc_code)
        .replace("{root_cause}", diagnosis.root_cause)
        .replace("{fix_direction}", diagnosis.fix_direction)
        .replace("{broken_selector}", broken_selector)
    )


def parse_response(
    raw_text: str, test_case_id: str, original_selector: str
) -> HealResult:
    """Parse LLM JSON → HealResult. Returns zero-confidence on failure."""
    try:
        data = json.loads(_strip_fences(raw_text))
        return HealResult(**data)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        logger.error(
            "A6 parse failed", extra={"error": str(exc), "raw_preview": raw_text[:200]}
        )
        return HealResult(
            test_case_id=test_case_id,
            original_selector=original_selector,
            fixed_selector="",
            strategy="unknown",
            confidence=0.0,
            log="Cannot heal: LLM output could not be parsed",
        )


def can_heal(diagnosis: FailureDiagnosis) -> bool:
    """Only TOOL_SELECTION_WRONG is healable by A6."""
    return diagnosis.sfc_code == HEALABLE_SFC_CODE
