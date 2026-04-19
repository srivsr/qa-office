"""
Planner service — business logic for A10 Planner.
Risk scoring, test ordering, plan parsing, reflection comparison.
No LLM calls here — only data transformation and prompt building.
"""

import json
import logging
import re
from typing import Any, Dict, List, Tuple

from schemas import ReflectionInsight, RiskScore, TestPlan

logger = logging.getLogger(__name__)

_COMPLIANCE_MODULES = {"Payroll", "Attendance", "Compliance", "Onboarding", "Aadhaar"}
_RISK_WEIGHTS = {
    "failure_frequency": 0.40,
    "compliance_criticality": 0.30,
    "self_heal_count": 0.20,
    "time_since_last_pass": 0.10,
}


def compute_risk_score(module: str, records: List[Dict]) -> RiskScore:
    """Compute weighted risk score for a module from A9 history records."""
    if not records:
        is_compliance = module in _COMPLIANCE_MODULES
        return RiskScore(
            module=module,
            score=0.5,
            compliance_criticality=0.70 if is_compliance else 0.0,
            rationale="No history — neutral score assigned.",
        )

    total = len(records)
    failures = sum(1 for r in records if r.get("status") in ("failed", "error"))
    heals = sum(
        1
        for r in records
        if r.get("record_type") == "selector" and r.get("payload", {}).get("healed")
    )
    last_pass_days = _days_since_last_pass(records)
    compliance_crit = (
        0.70 if module in _COMPLIANCE_MODULES else _compute_compliance(records)
    )

    failure_freq = round(failures / total, 3) if total else 0.0
    heal_norm = min(heals / 5.0, 1.0)
    time_norm = min(last_pass_days / 30.0, 1.0)

    score = round(
        failure_freq * _RISK_WEIGHTS["failure_frequency"]
        + compliance_crit * _RISK_WEIGHTS["compliance_criticality"]
        + heal_norm * _RISK_WEIGHTS["self_heal_count"]
        + time_norm * _RISK_WEIGHTS["time_since_last_pass"],
        3,
    )

    return RiskScore(
        module=module,
        score=min(score, 1.0),
        failure_frequency=failure_freq,
        compliance_criticality=compliance_crit,
        self_heal_count=heals,
        time_since_last_pass_days=last_pass_days,
        rationale=f"{failures}/{total} runs failed. Heals: {heals}. Days since pass: {last_pass_days:.0f}.",
    )


def order_by_risk(test_cases: List[Any], risk_map: Dict[str, RiskScore]) -> List[Any]:
    """Order test cases by module risk score, highest first."""
    return sorted(
        test_cases,
        key=lambda tc: -risk_map.get(tc.module, RiskScore(module=tc.module)).score,
    )


def build_plan_prompt(
    template: str, run_request: Any, tc_ids: List[str], history: Dict[str, List[Dict]]
) -> str:
    """Fill planner prompt template with run context and history summary."""
    history_lines = []
    for mod, recs in history.items():
        rs = compute_risk_score(mod, recs)
        history_lines.append(
            f"  {mod}: failures={rs.failure_frequency:.0%}, heals={rs.self_heal_count}, "
            f"days_since_pass={rs.time_since_last_pass_days:.0f}, compliance={rs.compliance_criticality:.1f}"
        )
    return (
        template.replace("{run_id}", "unknown")
        .replace(
            "{mission_type}", run_request.mission_type if run_request else "regression"
        )
        .replace("{persona}", run_request.persona if run_request else "default")
        .replace("{test_case_ids}", json.dumps(tc_ids))
        .replace(
            "{risk_history}", "\n".join(history_lines) or "  No history available."
        )
    )


def parse_plan_response(raw: str, test_cases: List[Any], run_id: str) -> TestPlan:
    """Parse LLM plan response. Falls back to identity order on failure."""
    try:
        data = json.loads(_strip_fences(raw))
        return TestPlan(
            run_id=run_id,
            ordered_test_case_ids=data.get(
                "ordered_test_case_ids", [tc.id for tc in test_cases]
            ),
            risk_scores=[RiskScore(**rs) for rs in data.get("risk_scores", [])],
            rationale=data.get("rationale", ""),
            confidence=float(data.get("confidence", 0.7)),
        )
    except Exception as exc:
        logger.warning("Plan parse failed — using identity order: %s", exc)
        return TestPlan(
            run_id=run_id,
            ordered_test_case_ids=[tc.id for tc in test_cases],
            rationale="Parse failure — natural order applied.",
            confidence=0.5,
        )


def reorder_by_plan(test_cases: List[Any], plan: TestPlan) -> List[Any]:
    """Reorder test cases to match plan ordering."""
    order = {tc_id: i for i, tc_id in enumerate(plan.ordered_test_case_ids)}
    return sorted(test_cases, key=lambda tc: order.get(tc.id, len(order)))


def compute_accuracy(
    plan: TestPlan, results: List[Any]
) -> Tuple[float, List[str], List[str]]:
    """Return (accuracy, predicted_high_risk_ids, actual_failure_ids)."""
    n = len(plan.ordered_test_case_ids)
    top_half = set(plan.ordered_test_case_ids[: max(n // 2, 1)])
    actual_failures = [
        r.test_case_id for r in results if r.status in ("failed", "error")
    ]
    if not actual_failures:
        return 1.0, list(top_half), []
    overlap = len(top_half & set(actual_failures))
    accuracy = round(overlap / len(actual_failures), 3)
    return accuracy, list(top_half), actual_failures


def build_reflection_prompt(
    template: str, plan: TestPlan, results: List[Any], run_id: str
) -> str:
    """Fill reflection prompt with prediction vs actual comparison data."""
    accuracy, predicted, actual_failures = compute_accuracy(plan, results)
    scores_summary = (
        "\n".join(f"  {rs.module}: score={rs.score:.2f}" for rs in plan.risk_scores)
        or "  No module scores recorded."
    )
    return (
        template.replace("{run_id}", run_id)
        .replace("{predicted_high_risk}", json.dumps(predicted))
        .replace("{actual_failures}", json.dumps(actual_failures))
        .replace("{prediction_accuracy}", str(accuracy))
        .replace("{used_scores}", scores_summary)
    )


def parse_reflection(
    raw: str, plan: TestPlan, results: List[Any], run_id: str
) -> ReflectionInsight:
    """Parse LLM reflection response into ReflectionInsight."""
    accuracy, predicted, actual_failures = compute_accuracy(plan, results)
    try:
        data = json.loads(_strip_fences(raw))
        return ReflectionInsight(
            run_id=run_id,
            predicted_high_risk=predicted,
            actual_failures=actual_failures,
            prediction_accuracy=float(data.get("prediction_accuracy", accuracy)),
            miscalibrated_modules=data.get("miscalibrated_modules", []),
            weight_adjustments=data.get("weight_adjustments", {}),
            rationale=data.get("rationale", ""),
        )
    except Exception as exc:
        logger.warning("Reflection parse failed: %s", exc)
        return ReflectionInsight(
            run_id=run_id,
            predicted_high_risk=predicted,
            actual_failures=actual_failures,
            prediction_accuracy=accuracy,
            rationale="Parse failure — no weight adjustments applied.",
        )


def _days_since_last_pass(records: List[Dict]) -> float:
    """Estimate days since module last passed (rough heuristic from records)."""
    import time

    passes = [r for r in records if r.get("status") == "passed"]
    if not passes:
        return 30.0
    return max(0.0, min((time.time() - 1_745_000_000) / 86400.0, 30.0))


def _compute_compliance(records: List[Dict]) -> float:
    """Derive compliance criticality from record payloads."""
    for r in records:
        if r.get("payload", {}).get("is_compliance_data"):
            return 0.70
    return 0.0


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()
