"""
A13 Environment Guardian — verify and monitor test environment health.
One job: EnvConfig → AgentResult(artifacts={"health_status": HealthStatus}).

Output status:
  "success"  → healthy environment, proceed
  "review"   → degraded — proceed with caution, flag for human
  "error"    → unavailable — A11 must abort mission

Injectable llm and memory for testing.
"""

import logging
import time
from pathlib import Path
from typing import Any, Optional

from config.settings import settings as default_settings
from schemas import AgentResult, EnvConfig, MemoryWrite
from services import guardian_service
from tools.llm_client import LLMClient

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parents[1] / "prompts"


class A13EnvGuardian:
    """
    Pre-run environment health checks for the target application.
    Writes health history to A9 for trend analysis.
    """

    def __init__(
        self,
        settings=None,
        llm: Optional[Any] = None,
        memory: Optional[Any] = None,
    ) -> None:
        self._settings = settings or default_settings
        self._llm = llm or LLMClient(
            model=self._settings.a13_model, settings=self._settings
        )
        self._memory = memory
        self._prompt = (_PROMPTS_DIR / "a13_guardian_v1.txt").read_text(encoding="utf-8")

    def run(
        self,
        env_config: EnvConfig,
        run_id: Optional[str] = None,
    ) -> AgentResult:
        run_id = run_id or "unknown"
        t0 = time.time()
        logger.info("A13 start", extra={"run_id": run_id, "url": env_config.app_url})

        checks = guardian_service.run_prechecks(env_config, run_id)
        health = guardian_service.classify_health(
            checks, self._llm, self._prompt, run_id
        )

        if self._memory:
            self._memory.write(
                MemoryWrite(
                    source_agent="A13",
                    record_type="insight",
                    run_id=run_id,
                    test_case_id="ALL",
                    payload={"health_status": health.model_dump()},
                )
            )

        ms = int((time.time() - t0) * 1000)
        logger.info(
            "A13 complete",
            extra={"run_id": run_id, "status": health.status, "duration_ms": ms},
        )

        if health.status == "unavailable":
            return AgentResult(
                status="error",
                confidence=1.0,
                error_code="TOOL_UNAVAILABLE",
                error_message=health.error_message or "Environment unavailable",
                artifacts={"health_status": health.model_dump()},
                metrics={"duration_ms": ms},
            )

        return AgentResult(
            status="review" if health.status == "degraded" else "success",
            confidence=health.overall_score,
            review_required=health.status == "degraded",
            artifacts={"health_status": health.model_dump()},
            metrics={"duration_ms": ms},
        )
