"""
Locator service — A3 business logic: prompt building + selector response parsing.
"""

import json
import logging
import re

from pydantic import ValidationError

from schemas import ExecutableIntent, SelectorResult

logger = logging.getLogger(__name__)


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def build_prompt(template: str, intent: ExecutableIntent, module: str = "General") -> str:
    """Fill prompt template with intent data. Batch all steps in one call."""
    steps_text = "\n".join(
        f"{s.step_number}. action={s.playwright_action} selector={s.selector} value={s.value}"
        for s in intent.steps
    )
    return (
        template.replace("{test_case_id}", intent.test_case_id)
        .replace("{module}", module)
        .replace("{steps}", steps_text)
    )


def parse_response(raw_text: str, test_case_id: str) -> SelectorResult:
    """Parse LLM JSON → SelectorResult. Zero-confidence on failure."""
    try:
        data = json.loads(_strip_fences(raw_text))
        return SelectorResult(**data)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        logger.error(
            "A3 parse failed", extra={"error": str(exc), "raw_preview": raw_text[:200]}
        )
        return SelectorResult(
            test_case_id=test_case_id, selectors=[], overall_confidence=0.0
        )
