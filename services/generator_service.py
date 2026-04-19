"""
Generator service — A0 business logic: prompt building + LLM response parsing.
Converts plain-English requirement descriptions into list[TestCase].
"""

import json
import logging
import re

from pydantic import BaseModel, Field, ValidationError

from schemas import TestCase

logger = logging.getLogger(__name__)


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


DEFAULT_COUNT = 4
DEFAULT_MODULE = "General"
DEFAULT_PRIORITY = "Medium"


class GeneratedCaseRaw(BaseModel):
    """Schema for a single LLM-generated test case before coercion to TestCase."""

    id: str
    module: str
    description: str
    steps: list[str]
    expected_result: str
    priority: str = "Medium"
    requires_live_verification: bool = False


class GeneratorOutput(BaseModel):
    """Full LLM response schema for test case generation."""

    test_cases: list[GeneratedCaseRaw] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    coverage_note: str = ""


def build_prompt(
    template: str,
    requirement: str,
    module: str = DEFAULT_MODULE,
    priority: str = DEFAULT_PRIORITY,
    count: int = DEFAULT_COUNT,
    app_url: str = "",
    app_name: str = "",
) -> str:
    """Fill prompt template with requirement context."""
    return (
        template.replace("{requirement}", requirement)
        .replace("{module}", module)
        .replace("{priority}", priority)
        .replace("{count}", str(count))
        .replace("{app_url}", app_url or "the application URL")
        .replace("{app_name}", app_name or "the application")
    )


def parse_response(raw_text: str, module: str = DEFAULT_MODULE) -> GeneratorOutput:
    """
    Parse LLM JSON → GeneratorOutput.
    On any parse failure → zero-confidence empty output (never crash pipeline).
    """
    try:
        data = json.loads(_strip_fences(raw_text))
        output = GeneratorOutput(**data)
        # Normalise: ensure module is set if LLM omitted it
        for tc in output.test_cases:
            if not tc.module:
                tc.module = module
        return output
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        logger.error(
            "A0 parse failed", extra={"error": str(exc), "raw_preview": raw_text[:200]}
        )
        return GeneratorOutput(
            test_cases=[],
            confidence=0.0,
            coverage_note=f"LLM output could not be parsed: {exc}",
        )


def to_test_cases(output: GeneratorOutput) -> list[TestCase]:
    """Convert GeneratorOutput → list[TestCase] for pipeline consumption."""
    result = []
    for raw in output.test_cases:
        # Strip numbering prefixes from steps if LLM included them inline
        clean_steps = [_strip_step_prefix(s) for s in raw.steps if s.strip()]
        result.append(
            TestCase(
                id=raw.id,
                module=raw.module,
                description=raw.description,
                steps=clean_steps,
                expected_result=raw.expected_result,
                priority=_normalise_priority(raw.priority),
                requires_live_verification=raw.requires_live_verification,
            )
        )
    return result


def _strip_step_prefix(step: str) -> str:
    """Remove '1. ' or '1) ' numbering the LLM sometimes adds."""
    return step.lstrip("0123456789").lstrip(". )").strip() or step


def _normalise_priority(raw: str) -> str:
    v = (raw or "").strip().lower()
    if v in ("p1", "high", "critical"):
        return "High"
    if v in ("p3", "low"):
        return "Low"
    return "Medium"
