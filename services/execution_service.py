"""
Execution service — type conversion and retry logic for A4 Executor.
Browser I/O goes through tools/browser_tool.py; this layer handles business rules.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from schemas import ExecutionResult, StepResult, TestCase
from tools.browser_tool import BrowserTool

logger = logging.getLogger(__name__)


def to_browser_dict(tc: TestCase) -> dict:
    """Convert TestCase → dict format expected by BrowserTool / qa-os."""
    import re
    route = "/"
    for step in tc.steps:
        m = re.search(r"navigate\s+to\s+(\S+)", step, re.IGNORECASE)
        if m:
            url = m.group(1).rstrip(".,;")
            try:
                from urllib.parse import urlparse
                path = urlparse(url).path
                if path:
                    route = path
            except Exception:
                pass
            break
    return {
        "id": tc.id,
        "title": tc.description,
        "steps": tc.steps,
        "expected_result": tc.expected_result,
        "priority": tc.priority,
        "module": tc.module,
        "test_data": {},
        "route": route,
    }


def to_execution_result(
    tc: TestCase, raw: dict, run_id: str, retry_count: int = 0
) -> ExecutionResult:
    """Convert raw browser result dict → typed ExecutionResult."""
    raw_status = raw.get("status", "error")
    if raw_status in ("pass", "passed", "success"):
        status = "passed"
    elif raw_status == "error":
        status = "error"
    else:
        status = "failed"

    screenshot_paths = []
    if raw.get("screenshot_path"):
        screenshot_paths.append(raw["screenshot_path"])
    elif raw.get("screenshot_base64"):
        screenshot_paths.append(f"screenshots/{run_id}/{tc.id}_final.png")

    return ExecutionResult(
        test_case_id=tc.id,
        status=status,
        duration_ms=raw.get("execution_time_ms", 0),
        retry_count=retry_count,
        timestamp=datetime.now(timezone.utc).isoformat(),
        error_message=raw.get("error_message"),
        screenshot_paths=screenshot_paths,
        step_results=[
            StepResult(step_number=i + 1, action=step, status="unknown", duration_ms=0)
            for i, step in enumerate(tc.steps)
        ],
    )


async def execute_with_retry(
    tc: TestCase,
    app_url: str,
    run_id: str,
    settings,
    browser: BrowserTool,
    execution_mode: Optional[str] = None,
    openai_api_key: Optional[str] = None,
) -> ExecutionResult:
    """
    Execute one test case with retry on transient failures (FR2).
    Retries: up to max_retries, exponential backoff.
    Retries only for transient failures — not validation/auth errors.
    execution_mode: page_check | scriptless | scripted (default from settings)
    """
    raw_list = await browser.execute(
        [to_browser_dict(tc)], app_url,
        execution_mode=execution_mode,
        openai_api_key=openai_api_key,
    )
    result = to_execution_result(tc, raw_list[0], run_id)

    if result.status in ("failed", "error"):
        for attempt in range(1, settings.max_retries + 1):
            backoff = (settings.retry_backoff_base_ms * (2 ** (attempt - 1))) / 1000
            logger.info(
                "Retry %d/%d for %s (backoff %.1fs)",
                attempt,
                settings.max_retries,
                tc.id,
                backoff,
            )
            await asyncio.sleep(backoff)
            raw_list = await browser.execute(
                [to_browser_dict(tc)], app_url,
                execution_mode=execution_mode,
                openai_api_key=openai_api_key,
            )
            result = to_execution_result(tc, raw_list[0], run_id, retry_count=attempt)
            if result.status == "passed":
                logger.info("%s recovered on retry %d", tc.id, attempt)
                return result

    return result
