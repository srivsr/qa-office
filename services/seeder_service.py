"""
Seeder service — business logic for A12 Data Seeder.
Generates seed recipes via LLM and applies them (dry-run simulation).
Safety: never touches production URLs. Never uses real PII.
"""

import json
import logging
import re
from typing import Any, List

from schemas import SeedRecipe, SeedResult

logger = logging.getLogger(__name__)

_PROD_URL_PATTERNS = ("//prod.", ".prod.", "-prod.", "production")


def is_safe_url(url: str) -> bool:
    """Return False if URL looks like production."""
    return not any(p in url.lower() for p in _PROD_URL_PATTERNS)


def generate_recipes(
    llm: Any,
    prompt_template: str,
    modules: List[str],
    run_id: str,
) -> List[SeedRecipe]:
    """Call LLM to generate seed recipes for the given modules."""
    if not modules:
        return []
    try:
        prompt = prompt_template.replace("{modules}", json.dumps(modules)).replace(
            "{run_id}", run_id
        )
        raw = llm.complete(prompt)
        data = _parse_json(raw)
        return [SeedRecipe(**r) for r in data.get("recipes", [])]
    except Exception as exc:
        logger.warning("Seed recipe generation failed: %s", exc)
        return []


def apply_recipes(
    recipes: List[SeedRecipe],
    app_url: str,
    run_id: str,
) -> SeedResult:
    """Simulate applying seed recipes. Real DB writes happen in Phase 6+."""
    warnings = [
        f"Compliance seed requires A7 review: {r.module}/{r.action}"
        for r in recipes
        if r.is_compliance_data
    ]
    return SeedResult(
        run_id=run_id,
        seeded=len(recipes) > 0,
        modules=list({r.module for r in recipes}),
        recipes_applied=len(recipes),
        warnings=warnings,
    )


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}
