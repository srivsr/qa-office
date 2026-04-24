"""
Parallel Test Executor
Runs multiple tests simultaneously using browser contexts.
Uses subprocess approach for Windows compatibility.
"""

import asyncio
import base64
import json
import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _check_text_assertions(steps: list, page_content: str) -> list:
    """
    Extract quoted text from Assert/Verify steps and check each against page content.
    Returns list of failure descriptions (empty = all assertions pass).
    """
    import re
    content_lower = page_content.lower()
    failed = []
    for step in steps:
        if not re.search(r'\b(?:assert|verify|check)\b', step, re.IGNORECASE):
            continue
        for m in re.finditer(r"['\"]([^'\"]{3,})['\"]", step):
            text = m.group(1)
            if text.lower() not in content_lower:
                failed.append(f"'{text}' not found")
    return failed


@dataclass
class ExecutionConfig:
    """Configuration for test execution"""
    app_url: str
    headless: bool = True
    parallel: bool = False
    max_workers: int = 4
    timeout_ms: int = 60000
    screenshot_on_pass: bool = True
    screenshot_on_fail: bool = True
    auth_config: Dict[str, Any] = None


class ParallelTestExecutor:
    """
    Execute tests in parallel using multiple browser contexts.

    Features:
    - Configurable worker count (default: 4)
    - Each worker gets its own browser context (isolated)
    - Semaphore to limit concurrency
    - Progress tracking
    """

    def __init__(self, config: ExecutionConfig):
        self.config = config
        self._browser = None
        self._semaphore = None
        self._progress = {"completed": 0, "total": 0}

    async def execute_all(
        self,
        test_cases: List[Dict[str, Any]],
        progress_callback: Callable = None
    ) -> List[Dict[str, Any]]:
        """
        Execute all test cases.

        Args:
            test_cases: List of test cases to execute
            progress_callback: Optional callback(completed, total, current_test)

        Returns:
            List of results with same order as input
        """

        if not test_cases:
            return []

        self._progress = {"completed": 0, "total": len(test_cases)}

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright not installed")
            return [
                {**tc, "status": "error", "error_message": "Playwright not installed"}
                for tc in test_cases
            ]

        results = []

        async with async_playwright() as p:
            self._browser = await p.chromium.launch(headless=self.config.headless)

            try:
                if self.config.parallel:
                    results = await self._execute_parallel(
                        test_cases, progress_callback
                    )
                else:
                    results = await self._execute_sequential(
                        test_cases, progress_callback
                    )
            finally:
                await self._browser.close()

        return results

    async def _execute_parallel(
        self,
        test_cases: List[Dict[str, Any]],
        progress_callback: Callable = None
    ) -> List[Dict[str, Any]]:
        """Execute tests in parallel with limited concurrency"""

        self._semaphore = asyncio.Semaphore(self.config.max_workers)

        logger.info(f"Starting PARALLEL execution: {len(test_cases)} tests, {self.config.max_workers} workers")

        tasks = [
            self._execute_with_semaphore(tc, idx, progress_callback)
            for idx, tc in enumerate(test_cases)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    **test_cases[i],
                    "status": "error",
                    "error_message": str(result)
                })
            else:
                processed_results.append(result)

        return processed_results

    async def _execute_with_semaphore(
        self,
        test_case: Dict[str, Any],
        index: int,
        progress_callback: Callable = None
    ) -> Dict[str, Any]:
        """Execute single test with semaphore control"""

        async with self._semaphore:
            logger.debug(f"Worker acquired for TC-{index+1}: {test_case.get('id', 'unknown')}")

            context = await self._browser.new_context()
            page = await context.new_page()

            try:
                result = await self._execute_single_test(page, test_case)
            finally:
                await context.close()

            self._progress["completed"] += 1
            if progress_callback:
                try:
                    progress_callback(
                        self._progress["completed"],
                        self._progress["total"],
                        test_case.get("id", "")
                    )
                except:
                    pass

            logger.debug(f"Completed TC-{index+1}: {result.get('status')}")
            return result

    async def _execute_sequential(
        self,
        test_cases: List[Dict[str, Any]],
        progress_callback: Callable = None
    ) -> List[Dict[str, Any]]:
        """Execute tests one by one (original behavior)"""

        logger.info(f"Starting SEQUENTIAL execution: {len(test_cases)} tests")

        results = []

        context = await self._browser.new_context()
        page = await context.new_page()

        try:
            for idx, tc in enumerate(test_cases):
                result = await self._execute_single_test(page, tc)
                results.append(result)

                self._progress["completed"] += 1
                if progress_callback:
                    try:
                        progress_callback(
                            self._progress["completed"],
                            self._progress["total"],
                            tc.get("id", "")
                        )
                    except:
                        pass
        finally:
            await context.close()

        return results

    async def _execute_single_test(
        self,
        page,
        tc: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a single test case"""

        result = {
            **tc,
            "status": "pending",
            "screenshot_base64": None,
            "error_message": None,
            "actual_result": None,
            "execution_time_ms": 0,
        }

        start_time = datetime.now()

        try:
            route = tc.get("route", "/")
            url = f"{self.config.app_url.rstrip('/')}{route}"

            await page.goto(url, wait_until='domcontentloaded', timeout=self.config.timeout_ms)
            await page.wait_for_load_state('load', timeout=self.config.timeout_ms)
            await asyncio.sleep(0.5)

            actual_url = page.url
            title = await page.title()
            content = await page.content()

            # Detect redirect away from target domain (e.g. Clerk auth wall, SSO)
            expected_base = self.config.app_url.rstrip('/')
            if expected_base not in actual_url:
                result["status"] = "failed"
                result["error_message"] = (
                    f"Redirected away from target — expected {url}, "
                    f"landed on {actual_url}. Page may require authentication."
                )
            else:
                # Check text assertions extracted from step descriptions
                failed_assertions = _check_text_assertions(tc.get("steps", []), content)
                if failed_assertions:
                    result["status"] = "failed"
                    result["error_message"] = (
                        f"Assertions not found on page: "
                        + "; ".join(failed_assertions[:3])
                    )
                elif len(content) > 500:
                    result["status"] = "passed"
                    result["actual_result"] = f"Page loaded: {title}"
                else:
                    result["status"] = "failed"
                    result["error_message"] = "Page content too short"

            # Always capture screenshot so customer can see actual page state
            try:
                screenshot_bytes = await page.screenshot(full_page=False)
                result["screenshot_base64"] = base64.b64encode(screenshot_bytes).decode('utf-8')
            except Exception:
                pass

        except asyncio.TimeoutError:
            result["status"] = "failed"
            result["error_message"] = f"Timeout loading page after {self.config.timeout_ms}ms"
            try:
                screenshot_bytes = await page.screenshot(full_page=False)
                result["screenshot_base64"] = base64.b64encode(screenshot_bytes).decode('utf-8')
            except Exception:
                pass

        except Exception as e:
            result["status"] = "failed"
            result["error_message"] = str(e)
            try:
                screenshot_bytes = await page.screenshot(full_page=False)
                result["screenshot_base64"] = base64.b64encode(screenshot_bytes).decode('utf-8')
            except Exception:
                pass

        result["execution_time_ms"] = int((datetime.now() - start_time).total_seconds() * 1000)
        return result


async def execute_tests_v2(
    test_cases: List[Dict[str, Any]],
    app_url: str,
    headless: bool = True,
    parallel: bool = False,
    max_workers: int = 4,
    auth_config: Dict[str, Any] = None,
    progress_callback: Callable = None,
    execution_mode: str = "auto",
    screenshot_dir: str = None,
) -> List[Dict[str, Any]]:
    """Execute tests using ParallelTestExecutor (direct Playwright, no subprocess)."""
    if not test_cases:
        return []

    executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH") or None
    config = ExecutionConfig(
        app_url=app_url,
        headless=headless,
        parallel=parallel,
        max_workers=max_workers,
        auth_config=auth_config or {},
    )

    executor = ParallelTestExecutor(config)

    # Patch launch to use system chromium if available
    _orig_execute_all = executor.execute_all

    async def _patched_execute_all(tcs, cb=None):
        from playwright.async_api import async_playwright
        results = []
        async with async_playwright() as p:
            launch_kwargs = {"headless": config.headless}
            if executable_path:
                launch_kwargs["executable_path"] = executable_path
            try:
                executor._browser = await p.chromium.launch(**launch_kwargs)
            except Exception as exc:
                return [
                    {**tc, "status": "error", "error_message": f"Browser launch failed: {exc}"}
                    for tc in tcs
                ]
            try:
                if config.parallel:
                    results = await executor._execute_parallel(tcs, cb)
                else:
                    results = await executor._execute_sequential(tcs, cb)
            finally:
                await executor._browser.close()
        return results

    try:
        logger.info("[EXEC] Starting direct Playwright execution: %d tests", len(test_cases))
        return await _patched_execute_all(test_cases, progress_callback)
    except Exception as exc:
        logger.error("[EXEC] Execution error: %s", exc)
        return [
            {**tc, "status": "error", "error_message": f"Execution error: {exc}"}
            for tc in test_cases
        ]
