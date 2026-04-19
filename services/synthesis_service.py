"""
Synthesis service — emergent pattern detection for A11 QA Director.
Uses Opus LLM (via injected llm parameter) for cross-run signal synthesis.
Rule-based detection first; LLM used only for interpretation.
"""

import json
import logging
import re
from collections import Counter
from typing import Any, List

from schemas import ProactiveAlert

logger = logging.getLogger(__name__)

_INSTABILITY_HEAL_THRESHOLD = 3
_SYSTEMIC_BUG_CASE_THRESHOLD = 3
_DRIFT_CONFIDENCE_DROP = 0.10
_MAX_ALERTS = 5


def detect_instability(heal_records: List[dict]) -> List[ProactiveAlert]:
    """Rule-based: module healed >= 3 times → instability alert."""
    counts: Counter = Counter()
    for r in heal_records:
        module = r.get("module", "Unknown")
        if r.get("payload", {}).get("healed"):
            counts[module] += 1

    alerts = []
    for module, count in counts.most_common():
        if count >= _INSTABILITY_HEAL_THRESHOLD:
            severity = "high" if count >= 5 else "medium"
            alerts.append(
                ProactiveAlert(
                    alert_type="instability",
                    module=module,
                    signal=f"Selector healed {count} times recently — UI component may be unstable.",
                    severity=severity,
                    recommendation=f"Add data-testid attributes to {module} controls or audit recent UI changes.",
                )
            )
    return alerts


def detect_systemic_bugs(failure_records: List[dict]) -> List[ProactiveAlert]:
    """Rule-based: same SFC root cause across >= 3 test cases → systemic bug."""
    cause_cases: dict = {}
    for r in failure_records:
        sfc = r.get("payload", {}).get("sfc_code", "")
        tc_id = r.get("test_case_id", "")
        module = r.get("module", "Unknown")
        if sfc and tc_id:
            if sfc not in cause_cases:
                cause_cases[sfc] = {"cases": set(), "modules": set()}
            cause_cases[sfc]["cases"].add(tc_id)
            cause_cases[sfc]["modules"].add(module)

    alerts = []
    for sfc, data in cause_cases.items():
        if len(data["cases"]) >= _SYSTEMIC_BUG_CASE_THRESHOLD:
            modules = ", ".join(sorted(data["modules"]))
            severity = "high" if len(data["cases"]) >= 5 else "medium"
            alerts.append(
                ProactiveAlert(
                    alert_type="systemic_bug",
                    module=modules,
                    signal=f"SFC code {sfc} appears in {len(data['cases'])} test cases across {modules}.",
                    severity=severity,
                    recommendation=f"Investigate product-level regression causing {sfc} across multiple modules.",
                )
            )
    return alerts


def detect_model_drift(confidence_records: List[dict]) -> List[ProactiveAlert]:
    """Rule-based: A2/A3 confidence declining > 10% over last 5 records per module."""
    by_module: dict = {}
    for r in confidence_records:
        mod = r.get("module", "Unknown")
        conf = r.get("payload", {}).get("confidence", None)
        if conf is not None:
            by_module.setdefault(mod, []).append(float(conf))

    alerts = []
    for module, confidences in by_module.items():
        if len(confidences) < 5:
            continue
        recent = confidences[-5:]
        drop = recent[0] - recent[-1]
        if drop >= _DRIFT_CONFIDENCE_DROP:
            alerts.append(
                ProactiveAlert(
                    alert_type="model_drift",
                    module=module,
                    signal=f"A2/A3 confidence dropped {drop:.0%} over last 5 runs for {module}.",
                    severity="medium",
                    recommendation=f"Review test cases in {module} — UI may have changed since last update.",
                )
            )
    return alerts


def synthesize_alerts(
    a9: Any,
    llm: Any,
    prompt_template: str,
    test_cases: List[Any],
    run_id: str,
) -> List[ProactiveAlert]:
    """
    Full synthesis pipeline:
    1. Query A9 for heal, failure, and confidence records
    2. Rule-based detection (fast, no LLM)
    3. LLM synthesis for narrative-level patterns (Opus)
    4. Merge, deduplicate, cap at MAX_ALERTS
    """
    from schemas import MemoryQuery

    heal_recs, fail_recs, conf_recs = [], [], []
    for tc in test_cases[:10]:
        res = a9.query(
            MemoryQuery(query_type="run_history", test_case_id=tc.id, limit=10)
        )
        if res.success:
            heal_recs.extend(
                [r for r in res.records if r.get("record_type") == "selector"]
            )
            fail_recs.extend(
                [r for r in res.records if r.get("status") in ("failed", "error")]
            )
            conf_recs.extend(res.records)

    rule_alerts = (
        detect_instability(heal_recs)
        + detect_systemic_bugs(fail_recs)
        + detect_model_drift(conf_recs)
    )

    llm_alerts = _llm_synthesis(
        llm, prompt_template, heal_recs, fail_recs, conf_recs, run_id
    )
    merged = _merge_alerts(rule_alerts + llm_alerts)
    return merged[:_MAX_ALERTS]


def _llm_synthesis(
    llm, template, heal_recs, fail_recs, conf_recs, run_id
) -> List[ProactiveAlert]:
    """Call Opus LLM for narrative-level synthesis. Returns [] on any failure."""
    try:
        heal_counts = _summarize_heal_counts(heal_recs)
        root_clusters = _summarize_root_causes(fail_recs)
        conf_trends = _summarize_confidence(conf_recs)
        narratives = [
            r.get("payload", {}).get("narrative", "")
            for r in fail_recs[:10]
            if r.get("payload", {}).get("narrative")
        ]

        prompt = (
            template.replace("{run_id}", run_id)
            .replace("{narratives}", json.dumps(narratives[:5]))
            .replace("{heal_counts}", json.dumps(heal_counts))
            .replace("{confidence_trends}", json.dumps(conf_trends))
            .replace("{root_cause_clusters}", json.dumps(root_clusters))
        )
        raw = llm.complete(prompt)
        data = json.loads(_strip_fences(raw))
        return [ProactiveAlert(**a) for a in data.get("alerts", [])]
    except Exception as exc:
        logger.warning("LLM synthesis failed (non-fatal): %s", exc)
        return []


def _merge_alerts(alerts: List[ProactiveAlert]) -> List[ProactiveAlert]:
    """Deduplicate and sort by severity."""
    severity_order = {"high": 0, "medium": 1, "low": 2}
    seen = set()
    unique = []
    for a in sorted(alerts, key=lambda x: severity_order.get(x.severity, 9)):
        key = (a.alert_type, a.module[:20])
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique


def _summarize_heal_counts(records: List[dict]) -> dict:
    counts: Counter = Counter()
    for r in records:
        if r.get("payload", {}).get("healed"):
            counts[r.get("module", "Unknown")] += 1
    return dict(counts)


def _summarize_root_causes(records: List[dict]) -> dict:
    clusters: dict = {}
    for r in records:
        sfc = r.get("payload", {}).get("sfc_code", "")
        if sfc:
            clusters.setdefault(sfc, []).append(r.get("test_case_id", ""))
    return clusters


def _summarize_confidence(records: List[dict]) -> dict:
    by_module: dict = {}
    for r in records:
        mod = r.get("module", "Unknown")
        conf = r.get("payload", {}).get("confidence")
        if conf is not None:
            by_module.setdefault(mod, []).append(round(float(conf), 2))
    return by_module


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()
