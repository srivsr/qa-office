"""
A11 QA Director — master orchestrator for the QA Office pipeline.
One job: QAMission → AgentResult(artifacts={"mission_result": MissionResult}).
Pipeline: A13→A14(if stale)→A10(plan)→A12→A1→A2→A15(validate)→A3(cache-first)→A4(POM-first)→
          A5→A6→A7→A8→A10(reflect)→Synthesis.
A14 POM rebuild triggered if A6 repair rate >20% (a14_rebuild_threshold).
Uses Sonnet for routing; Opus (self._synthesis_llm) for emergent synthesis (ADR-018).
All pipeline business logic in services/director_service.py.
"""

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from agents.a09_memory_keeper import A9MemoryKeeper
from config.settings import settings as default_settings
from schemas import AgentResult, QAMission
from services import director_service, synthesis_service
from tools.llm_client import LLMClient

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parents[1] / "prompts"


class A11QADirector:
    """
    Top-level orchestrator. Injectable agents dict for full test isolation.
    Holds two LLM clients: Sonnet (routing) and Opus (emergent synthesis).
    """

    def __init__(
        self,
        settings=None,
        agents: Optional[Dict[str, Any]] = None,
        llm: Optional[Any] = None,
        synthesis_llm: Optional[Any] = None,
    ) -> None:
        self._settings = settings or default_settings
        self._injected = agents or {}
        self._cache: Dict[str, Any] = {}
        self._llm = llm or LLMClient(
            model=self._settings.a11_model, settings=self._settings
        )
        self._synthesis_llm = synthesis_llm or LLMClient(
            model=self._settings.a11_opus_model, settings=self._settings
        )
        self._pattern_prompt = (_PROMPTS_DIR / "a11_patterns_v1.txt").read_text(encoding="utf-8")
        self._synthesis_prompt = (_PROMPTS_DIR / "a11_synthesis_v1.txt").read_text(encoding="utf-8")
        self._a9 = A9MemoryKeeper()

    def run(self, mission: QAMission, run_id: Optional[str] = None, stage_cb=None) -> AgentResult:
        run_id = run_id or uuid.uuid4().hex[:8]
        t0 = time.time()
        logger.info("A11 start", extra={"run_id": run_id, "url": mission.app_url})

        def _cb(name: str) -> None:
            if stage_cb:
                stage_cb(name)

        # A13 — health check (abort if unavailable)
        _cb("env_check")
        health = director_service.check_environment(
            mission.app_url, self._get("A13"), run_id
        )
        if health.status == "unavailable":
            return AgentResult(
                status="error",
                confidence=0.0,
                error_code="TOOL_UNAVAILABLE",
                error_message=health.error_message or "Environment unavailable",
            )

        # A14 — POM builder (run if pom_config provided or forced)
        pom_result = None
        if getattr(mission, "pom_config", None):
            _cb("pom_build")
            pom_result = self._run_a14(mission, run_id)

        # A1 — ingest test cases
        _cb("ingestion")
        a1_result = self._get("A1").run(mission.excel_path, run_id=run_id)
        if a1_result.status == "error":
            return AgentResult(
                status="error", confidence=0.0, error_message=a1_result.error_message
            )
        test_cases = a1_result.artifacts["test_cases"]

        # A10 — plan (query A9, score risks, order tests)
        plan = None
        if mission.run_request:
            _cb("planning")
            plan = director_service.plan_mission(
                mission.run_request, test_cases, self._get("A10"), run_id
            )
            test_cases = director_service.reorder_by_plan(test_cases, plan)

        # A12 — seed test data (when requested)
        seed_result = None
        if mission.seed_required:
            _cb("seeding")
            seed_result = director_service.seed_test_data(
                mission, self._get("A12"), self._get("A7"), run_id
            )

        # A2 + A15(validate) + A3 — interpret intent, validate assertions, scout selectors
        _cb("intent")
        paused_count = 0
        for tc in test_cases:
            ok = director_service.interpret_test_case(
                tc, self._get("A2"), self._get("A3"), self._get("A7"), run_id,
                app_name=mission.app_name,
                a15=self._get("A15"),
            )
            if not ok:
                paused_count += 1

        # A4 — execute all test cases (POM-first when available)
        _cb("executing")
        a4_result = self._get("A4").run(
            test_cases,
            app_url=mission.app_url,
            run_id=run_id,
            pom_result=pom_result,
            execution_mode=mission.execution_mode,
            openai_api_key=mission.openai_api_key,
            auth_email=mission.auth_email or None,
            auth_password=mission.auth_password or None,
            auth_type=mission.auth_type or None,
        )
        if a4_result.status == "error":
            return AgentResult(
                status="error", confidence=0.0, error_message=a4_result.error_message
            )
        results = a4_result.artifacts["results"]

        # A5 + A6 — diagnose failures and attempt heals
        _cb("failure_analysis")
        healed_count = 0
        for r in results:
            if r.status in ("failed", "error"):
                healed = director_service.diagnose_failure(
                    r, self._get("A5"), self._get("A6"), self._get("A7"), run_id
                )
                if healed:
                    healed_count += 1

        # Trigger A14 POM rebuild if A6 repair rate exceeds threshold
        total_failed = sum(1 for r in results if r.status in ("failed", "error"))
        if (
            total_failed > 0
            and healed_count / total_failed > self._settings.a14_rebuild_threshold
            and getattr(mission, "pom_config", None)
        ):
            logger.info(
                "A14 POM rebuild triggered — repair rate %.0f%%",
                healed_count / total_failed * 100,
                extra={"run_id": run_id},
            )
            _cb("pom_rebuild")
            pom_result = self._run_a14(mission, run_id, force=True)

        # A8 — build report (with compliance metadata)
        _cb("reporting")
        run_dir = str(Path(mission.output_dir) / run_id)
        a8_result = self._get("A8").run(
            test_cases,
            results,
            run_id=run_id,
            output_dir=run_dir,
            health_status=health,
            seed_result=seed_result,
        )

        # A10 — reflection (compare prediction vs actual)
        _cb("reflection")
        director_service.reflect_on_mission(plan, results, self._get("A10"), run_id)

        # A9 + Sonnet — cross-run pattern synthesis
        patterns = director_service.query_patterns(
            self._a9, self._llm, self._pattern_prompt, test_cases
        )

        # A9 + Opus — emergent proactive alert synthesis (ADR-018)
        alerts = synthesis_service.synthesize_alerts(
            self._a9, self._synthesis_llm, self._synthesis_prompt, test_cases, run_id
        )

        ms = int((time.time() - t0) * 1000)
        logger.info(
            "A11 complete",
            extra={
                "run_id": run_id,
                "total": len(results),
                "alerts": len(alerts),
                "duration_ms": ms,
            },
        )
        return director_service.build_mission_result(
            run_id,
            results,
            a8_result,
            patterns,
            paused_count,
            ms,
            health_status=health,
            seed_result=seed_result,
            proactive_alerts=alerts,
        )

    # ── A14 helper ──────────────────────────────────────────────────────────────

    def _run_a14(self, mission, run_id: str, force: bool = False) -> Optional[dict]:
        from schemas import AppConfig
        pom_cfg = getattr(mission, "pom_config", None)
        if not pom_cfg:
            return None
        app_config = AppConfig(
            base_url=mission.app_url,
            page_urls=pom_cfg.get("page_urls", []),
            auth_state=pom_cfg.get("auth_state"),
        )
        try:
            result = self._get("A14").run(app_config, run_id=run_id)
            if result.status in ("success", "review"):
                return result.artifacts.get("pom_result")
        except Exception as exc:
            logger.warning("A14 run failed (non-blocking): %s", exc, extra={"run_id": run_id})
        return None

    # ── agent registry ─────────────────────────────────────────────────────────

    def _get(self, name: str) -> Any:
        if name not in self._cache:
            self._cache[name] = self._injected.get(name) or self._build(name)
        return self._cache[name]

    def _build(self, name: str) -> Any:
        from agents.a01_ingestion import A1Ingestion
        from agents.a02_intent_interpreter import A2IntentInterpreter
        from agents.a03_locator_scout import A3LocatorScout
        from agents.a04_executor import A4Executor
        from agents.a05_failure_analyst import A5FailureAnalyst
        from agents.a06_self_healer import A6SelfHealer
        from agents.a07_reviewer import A7Reviewer
        from agents.a08_report_builder import A8ReportBuilder
        from agents.a10_planner import A10Planner
        from agents.a12_data_seeder import A12DataSeeder
        from agents.a13_env_guardian import A13EnvGuardian
        from agents.a14_pom_builder import A14POMBuilder
        from agents.a15_script_reviewer import A15ScriptReviewer

        _map: Dict[str, Any] = {
            "A1": lambda: A1Ingestion(),
            "A2": lambda: A2IntentInterpreter(self._settings),
            "A3": lambda: A3LocatorScout(self._settings),
            "A4": lambda: A4Executor(self._settings),
            "A5": lambda: A5FailureAnalyst(self._settings),
            "A6": lambda: A6SelfHealer(self._settings),
            "A7": lambda: A7Reviewer(self._settings),
            "A8": lambda: A8ReportBuilder(),
            "A10": lambda: A10Planner(self._settings),
            "A12": lambda: A12DataSeeder(self._settings),
            "A13": lambda: A13EnvGuardian(self._settings),
            "A14": lambda: A14POMBuilder(self._settings),
            "A15": lambda: A15ScriptReviewer(self._settings),
        }
        if name not in _map:
            raise ValueError(f"Unknown agent: {name}")
        return _map[name]()
