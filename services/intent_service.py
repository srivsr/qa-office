"""
Intent service — A2 business logic: prompt building + LLM response parsing.
"""

import json
import logging
import re

from pydantic import ValidationError

from schemas import ExecutableIntent, TestCase

logger = logging.getLogger(__name__)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences LLMs add despite being told not to."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def get_persona_context(persona: str, persona_template: str, app_context: str = "") -> str:
    """Extract focus/UI-path/access-level context for a named persona from the template file."""
    template = persona_template.replace("{app_context}", app_context or "the application under test")
    persona_key = (persona or "default").lower().replace(" ", "_")
    lines = template.splitlines()
    collecting = False
    context_lines = []
    for line in lines:
        if line.startswith(persona_key + ":") or (
            not collecting and line.strip().startswith(persona_key)
        ):
            collecting = True
            continue
        if collecting:
            if (
                line
                and not line[0].isspace()
                and ":" in line
                and not line.startswith(" ")
            ):
                break  # next persona block started
            context_lines.append(line.strip())
    context = " ".join(line for line in context_lines if line)
    return context or "Standard user — no specific persona context available."


def build_prompt(template: str, test_case: TestCase, persona_context: str = "") -> str:
    """Fill prompt template with test case data and optional persona context."""
    steps_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(test_case.steps))
    persona_label = test_case.persona or "default"
    persona_full = (
        f"{persona_label} — {persona_context}" if persona_context else persona_label
    )
    return (
        template.replace("{test_case_id}", test_case.id)
        .replace("{module}", test_case.module)
        .replace("{persona}", persona_full)
        .replace("{steps}", steps_text)
        .replace("{expected_result}", test_case.expected_result)
    )


def parse_response(raw_text: str, test_case_id: str) -> ExecutableIntent:
    """
    Parse LLM JSON response into ExecutableIntent.
    On any parse failure → return zero-confidence intent (never crash pipeline).
    """
    try:
        data = json.loads(_strip_fences(raw_text))
        return ExecutableIntent(**data)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        logger.error(
            "A2 parse failed",
            extra={"error": str(exc), "raw_preview": raw_text[:200]},
        )
        return ExecutableIntent(
            test_case_id=test_case_id,
            steps=[],
            confidence=0.0,
            persona="default",
            ambiguities=["LLM output could not be parsed"],
        )
