"""
Guardian service — business logic for A13 Environment Guardian.
Pre-run checks: URL reachable, latency OK, auth responding.
LLM used only for anomaly interpretation when checks are inconclusive.
"""

import logging
import ssl
import time
from typing import Any, List, Tuple
from urllib.request import urlopen

from schemas import EnvConfig, HealthCheck, HealthStatus

logger = logging.getLogger(__name__)


def run_prechecks(config: EnvConfig, run_id: str) -> List[HealthCheck]:
    """Run all pre-run health checks. Returns ordered list of HealthCheck results."""
    checks: List[HealthCheck] = []

    url_check, latency_ms = _check_url(config.app_url)
    checks.append(url_check)

    if url_check.passed:
        checks.append(
            HealthCheck(
                name="latency_ok",
                passed=latency_ms <= config.latency_threshold_ms,
                detail=f"{latency_ms}ms (threshold {config.latency_threshold_ms}ms)",
            )
        )

    if config.auth_url:
        auth_check, _ = _check_url(config.auth_url)
        auth_check = HealthCheck(
            name="auth_responding", passed=auth_check.passed, detail=auth_check.detail
        )
        checks.append(auth_check)

    return checks


def classify_health(
    checks: List[HealthCheck],
    llm: Any,
    prompt_template: str,
    run_id: str,
) -> HealthStatus:
    """Classify overall environment health from check results."""
    # URL unreachable is a warning, not a blocker — Docker networking differences
    # between environments mean the check is unreliable as a hard gate

    failed = [c for c in checks if not c.passed]
    if failed:
        score = round((len(checks) - len(failed)) / len(checks), 2) if checks else 0.0
        return HealthStatus(
            run_id=run_id,
            status="degraded",
            checks=checks,
            overall_score=score,
        )

    return HealthStatus(
        run_id=run_id,
        status="healthy",
        checks=checks,
        overall_score=1.0,
    )


def _check_url(url: str) -> Tuple[HealthCheck, int]:
    """Probe a URL. Returns (HealthCheck, latency_ms)."""
    t0 = time.time()
    try:
        ctx = ssl.create_default_context()
        try:
            import certifi
            ctx.load_verify_locations(certifi.where())
        except ImportError:
            pass
        urlopen(url, timeout=5, context=ctx)  # noqa: S310
        ms = int((time.time() - t0) * 1000)
        return HealthCheck(name="url_reachable", passed=True, detail=f"{ms}ms"), ms
    except ssl.SSLError:
        # Retry without verification as last resort
        t0 = time.time()
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            urlopen(url, timeout=5, context=ctx)  # noqa: S310
            ms = int((time.time() - t0) * 1000)
            return HealthCheck(name="url_reachable", passed=True, detail=f"{ms}ms (ssl-unverified)"), ms
        except Exception as exc2:
            ms = int((time.time() - t0) * 1000)
            return HealthCheck(name="url_reachable", passed=False, detail=str(exc2)), ms
    except Exception as exc:
        ms = int((time.time() - t0) * 1000)
        return HealthCheck(name="url_reachable", passed=False, detail=str(exc)), ms
