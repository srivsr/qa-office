"""
Director service — business logic for A11 QA Director.
Handles: A7 trigger rules, pipeline sub-steps, A9 pattern synthesis.
A11 agent orchestrates; this module contains all decision logic.
"""

import json
import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from schemas import (
    AgentResult,
    EnvConfig,
    HealthStatus,
    MemoryQuery,
    MissionResult,
    ProactiveAlert,
    ReviewRequest,
    SeedResult,
    TestPlan,
)

if TYPE_CHECKING:
    from agents.a07_reviewer import A7Reviewer
    from agents.a09_memory_keeper import A9MemoryKeeper
    from agents.a10_planner import A10Planner
    from agents.a12_data_seeder import A12DataSeeder
    from agents.a13_env_guardian import A13EnvGuardian

logger = logging.getLogger(__name__)

_A7_TRIGGER_SFC = {"GOAL_DRIFT", "SCOPE_CREEP", "IRREVERSIBLE_UNGATED"}


# ── A10 planning + reflection ─────────────────────────────────────────────────


def plan_mission(
    run_request: Any,
    test_cases: List[Any],
    a10: "A10Planner",
    run_id: str,
) -> Optional[TestPlan]:
    """Run A10 planning. Returns TestPlan or None on failure."""

    try:
        result = a10.run(run_request, test_cases, run_id=run_id)
        if result.status in ("success", "review") and "plan" in result.artifacts:
            return TestPlan(**result.artifacts["plan"])
    except Exception as exc:
        logger.warning("A10 planning failed (non-fatal): %s", exc)
    return None


def reorder_by_plan(test_cases: List[Any], plan: Optional[TestPlan]) -> List[Any]:
    """Reorder test cases by A10 plan. Returns unchanged list if plan is None."""
    if not plan:
        return test_cases
    from services import planner_service

    return planner_service.reorder_by_plan(test_cases, plan)


def reflect_on_mission(
    plan: Optional[TestPlan],
    results: List[Any],
    a10: "A10Planner",
    run_id: str,
) -> None:
    """Trigger A10 reflection after mission. Non-fatal — failures logged only."""
    if not plan:
        return
    try:
        a10.reflect(plan, results, run_id=run_id)
    except Exception as exc:
        logger.warning("A10 reflection failed (non-fatal): %s", exc)


# ── A13 + A12 pre-run steps ───────────────────────────────────────────────────


def check_environment(
    app_url: str,
    a13: "A13EnvGuardian",
    run_id: str,
) -> HealthStatus:
    """Run A13 pre-run checks. Returns HealthStatus regardless of outcome."""

    result = a13.run(EnvConfig(app_url=app_url), run_id=run_id)
    hs_data = result.artifacts.get("health_status", {})
    if hs_data:
        return HealthStatus(**hs_data)
    return HealthStatus(
        run_id=run_id,
        status="unavailable" if result.status == "error" else "healthy",
        overall_score=result.confidence,
        error_message=result.error_message,
    )


def seed_test_data(
    mission: Any,
    a12: "A12DataSeeder",
    a7: Any,
    run_id: str,
) -> SeedResult:
    """Run A12 seeder. Routes compliance PAUSE to A7. Returns SeedResult."""
    result = a12.run(mission, run_id=run_id)
    if result.status == "pause":
        dec = _route_pause(result, "A12", "ALL", run_id, a7)
        if not dec.approved:
            return SeedResult(
                run_id=run_id,
                seeded=False,
                warnings=["A7 rejected compliance seed"],
            )
    sr_data = result.artifacts.get("seed_result", {})
    if sr_data:
        return SeedResult(**sr_data)
    return SeedResult(run_id=run_id, seeded=False)


# ── A7 trigger rules ────────────────────────────────────────────────────────────


def should_invoke_a7(result: AgentResult, source_agent: str) -> bool:
    """Return True when A7 HITL gate must be invoked before continuing."""
    if result.status == "pause":
        return True
    if source_agent == "A6" and result.review_required:
        return True
    if source_agent == "A5" and result.error_code in _A7_TRIGGER_SFC:
        return True
    return False


def _route_pause(
    result: AgentResult,
    source_agent: str,
    tc_id: str,
    run_id: str,
    a7: "A7Reviewer",
) -> "ReviewDecision":  # noqa: F821
    from schemas import ReviewDecision

    try:
        return a7.run(
            ReviewRequest(
                run_id=run_id,
                test_case_id=tc_id,
                agent_result=result.model_dump(),
                reason=result.error_message or f"{source_agent} requires review",
                source_agent=source_agent,
            ),
            run_id=run_id,
        )
    except Exception as exc:
        logger.error("A7 escalation failed: %s", exc)
        from schemas import ReviewDecision

        return ReviewDecision(
            run_id=run_id, test_case_id=tc_id, approved=False, comment=str(exc)
        )


# ── Pipeline sub-steps ─────────────────────────────────────────────────────────


def interpret_test_case(
    tc: Any, a2: Any, a3: Any, a7: Any, run_id: str,
    app_name: str = "", a15: Any = None,
) -> bool:
    """Run A2 → A15(validate) → A3 for one test case. Returns False if PAUSE rejected."""
    a2_result = a2.run(tc, run_id=run_id, app_name=app_name)
    if should_invoke_a7(a2_result, "A2"):
        dec = _route_pause(a2_result, "A2", tc.id, run_id, a7)
        if not dec.approved:
            logger.info("A7 rejected A2 result for %s — skipping", tc.id)
            return False

    intent = a2_result.artifacts.get("intent")
    if not intent:
        return True

    from schemas import ExecutableIntent

    executable = ExecutableIntent(**intent)

    # A15 — validate assertions before execution (non-blocking, logs warnings)
    if a15 is not None:
        review = a15.review_script(executable)
        if review.warnings:
            logger.warning(
                "A15 assertion warnings for %s: %d flag(s)",
                tc.id,
                len(review.warnings),
                extra={"run_id": run_id, "warnings": review.warnings},
            )

    a3_result = a3.run(executable, run_id=run_id, module=getattr(tc, "module", "General"))
    if should_invoke_a7(a3_result, "A3"):
        dec = _route_pause(a3_result, "A3", tc.id, run_id, a7)
        if not dec.approved:
            logger.info("A7 rejected A3 result for %s — skipping", tc.id)
            return False

    return True


def diagnose_failure(result: Any, a5: Any, a6: Any, a7: Any, run_id: str) -> None:
    """Run A5 → A6 for one failed ExecutionResult. Routes to A7 as needed."""
    a5_result = a5.run(result, run_id=run_id)
    if should_invoke_a7(a5_result, "A5"):
        dec = _route_pause(a5_result, "A5", result.test_case_id, run_id, a7)
        if not dec.approved:
            return

    diag_data = a5_result.artifacts.get("diagnosis")
    if not diag_data:
        return

    from schemas import FailureDiagnosis

    diag = FailureDiagnosis(**diag_data)
    broken = result.step_results[0].action if result.step_results else ""
    a6_result = a6.run(diag, broken_selector=broken, run_id=run_id)
    if should_invoke_a7(a6_result, "A6"):
        _route_pause(a6_result, "A6", result.test_case_id, run_id, a7)


# ── Pattern synthesis ──────────────────────────────────────────────────────────


def query_patterns(
    a9: "A9MemoryKeeper",
    llm: Any,
    prompt_template: str,
    test_cases: List[Any],
) -> List[str]:
    """Query A9 run history, synthesize cross-agent patterns via LLM."""
    records: List[Dict] = []
    for tc in test_cases[:5]:
        res = a9.query(
            MemoryQuery(query_type="run_history", test_case_id=tc.id, limit=5)
        )
        records.extend(res.records)
    if not records:
        return []
    try:
        raw = llm.complete(
            prompt_template.replace("{records}", json.dumps(records[:20], indent=2))
        )
        return _parse_patterns(raw)
    except Exception as exc:
        logger.warning("Pattern synthesis failed: %s", exc)
        return []


def _parse_patterns(raw: str) -> List[str]:
    text = _strip_fences(raw)
    try:
        return json.loads(text).get("patterns", [])
    except (json.JSONDecodeError, AttributeError):
        return [
            ln.lstrip("- ").strip()
            for ln in raw.splitlines()
            if ln.strip().startswith("-")
        ]


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


# ── Result assembly ────────────────────────────────────────────────────────────


def build_mission_result(
    run_id: str,
    results: List[Any],
    a8_result: AgentResult,
    patterns: List[str],
    paused_count: int,
    ms: int,
    health_status: Optional["HealthStatus"] = None,
    seed_result: Optional["SeedResult"] = None,
    proactive_alerts: Optional[List["ProactiveAlert"]] = None,
) -> AgentResult:
    report = a8_result.artifacts.get("report")
    mr = MissionResult(
        run_id=run_id,
        total=len(results),
        passed=sum(1 for r in results if r.status == "passed"),
        failed=sum(1 for r in results if r.status == "failed"),
        error=sum(1 for r in results if r.status == "error"),
        pass_rate=report.pass_rate if report else 0.0,
        html_path=report.html_path if report else None,
        excel_path_report=report.excel_path if report else None,
        paused_count=paused_count,
        patterns=patterns,
        proactive_alerts=proactive_alerts or [],
    )
    return AgentResult(
        status="success",
        confidence=1.0,
        artifacts={"mission_result": mr.model_dump()},
        metrics={"duration_ms": ms},
    )
