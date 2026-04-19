"""
A12 Data Seeder — prepare test data state before A4 execution.
One job: QAMission + SeedConfig → AgentResult(artifacts={"seed_result": SeedResult}).

Safety gates:
- Refuses production URLs (IRREVERSIBLE_UNGATED)
- Routes compliance-data recipes to A7 for review (PAUSE)
- Writes seed recipe to A9 for chain-of-custody traceability
"""

import logging
import time
from pathlib import Path
from typing import Any, Optional

from config.settings import settings as default_settings
from schemas import AgentResult, MemoryWrite, QAMission, SeedConfig, SeedResult
from services import seeder_service
from tools.llm_client import LLMClient

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parents[1] / "prompts"


class A12DataSeeder:
    """
    Seeds test data before execution.
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
            model=self._settings.a12_model, settings=self._settings
        )
        self._memory = memory
        self._prompt = (_PROMPTS_DIR / "a12_seeder_v1.txt").read_text(encoding="utf-8")

    def run(
        self,
        mission: QAMission,
        run_id: Optional[str] = None,
    ) -> AgentResult:
        run_id = run_id or "unknown"
        t0 = time.time()
        logger.info("A12 start", extra={"run_id": run_id, "url": mission.app_url})

        if not seeder_service.is_safe_url(mission.app_url):
            logger.error("A12 blocked — production URL: %s", mission.app_url)
            return AgentResult(
                status="error",
                confidence=1.0,
                error_code="IRREVERSIBLE_UNGATED",
                error_message=f"Production URL blocked: {mission.app_url}",
            )

        seed_config = mission.seed_config or SeedConfig()
        recipes = seeder_service.generate_recipes(
            self._llm, self._prompt, seed_config.modules, run_id
        )

        compliance = [r for r in recipes if r.is_compliance_data]
        if compliance:
            modules = [r.module for r in compliance]
            logger.info("A12 compliance data — routing to A7: %s", modules)
            return AgentResult(
                status="pause",
                confidence=0.5,
                review_required=True,
                error_message=f"Compliance seed requires A7 review: {modules}",
                artifacts={
                    "seed_result": SeedResult(
                        run_id=run_id,
                        seeded=False,
                        warnings=[f"Compliance: {modules}"],
                    ).model_dump()
                },
            )

        seed_result = seeder_service.apply_recipes(recipes, mission.app_url, run_id)

        if self._memory:
            self._memory.write(
                MemoryWrite(
                    source_agent="A12",
                    record_type="insight",
                    run_id=run_id,
                    test_case_id="ALL",
                    payload={"seed_result": seed_result.model_dump()},
                )
            )

        ms = int((time.time() - t0) * 1000)
        logger.info(
            "A12 complete",
            extra={
                "run_id": run_id,
                "recipes": seed_result.recipes_applied,
                "duration_ms": ms,
            },
        )
        confidence = 0.95 if seed_result.seeded else 0.85
        return AgentResult(
            status="success",
            confidence=confidence,
            artifacts={"seed_result": seed_result.model_dump()},
            metrics={"duration_ms": ms},
        )
