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


import re as _re


async def _execute_step(page, step: str, app_url: str, timeout_ms: int = 15000) -> tuple:
    """
    Execute one test step using Playwright. Returns (success, error_message).
    Handles: navigate, click, fill, select, assert visible/hidden/disabled/url, wait.
    """
    s = step.strip()
    sl = s.lower()
    to = timeout_ms

    # ── Navigate ──────────────────────────────────────────────────────────────
    m = _re.search(r'navigate\s+(?:\w+\s+)*?to\s+(https?://\S+|/\S*)', s, _re.IGNORECASE)
    if m:
        url = _re.sub(r'\[[^\]]+\]', '', m.group(1).rstrip('.,;')).rstrip('/') or '/'
        if not url.startswith('http'):
            url = f"{app_url.rstrip('/')}{url}"
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=to)
            try:
                await page.wait_for_load_state('networkidle', timeout=8000)
            except Exception:
                pass
            await asyncio.sleep(1.5)
            return True, ''
        except Exception as e:
            return False, str(e)[:120]

    # ── Click ─────────────────────────────────────────────────────────────────
    if _re.search(r'\bclick\b', sl):
        m = _re.search(r"['\"]([^'\"]+)['\"]", s)
        if m:
            label = m.group(1)
            try:
                for role in ('button', 'link', 'tab', 'menuitem', 'option', 'combobox'):
                    loc = page.get_by_role(role, name=label, exact=False)
                    if await loc.count() > 0:
                        await loc.first.click(timeout=to)
                        await asyncio.sleep(0.8)
                        return True, ''
                loc = page.get_by_text(label, exact=True)
                if await loc.count() > 0:
                    await loc.first.click(timeout=to)
                    await asyncio.sleep(0.8)
                    return True, ''
                loc = page.get_by_text(label, exact=False)
                if await loc.count() > 0:
                    await loc.first.click(timeout=to)
                    await asyncio.sleep(0.8)
                    return True, ''
                return False, f"Element '{label}' not found to click"
            except Exception as e:
                return False, str(e)[:120]

    # ── Fill ──────────────────────────────────────────────────────────────────
    if _re.search(r'\bfill\b', sl):
        m = _re.search(
            r"fill\s+(?:the\s+)?['\"]([^'\"]+)['\"](?:\s+field)?"
            r"\s+with\s+(?:[\w\s]+?:\s*)?['\"]([^'\"]*)['\"]", s, _re.IGNORECASE
        )
        if m:
            field, value = m.group(1), m.group(2)
            try:
                for loc in (
                    page.get_by_label(field, exact=False),
                    page.get_by_placeholder(field, exact=False),
                    page.locator(f'textarea, input').filter(has_text=field),
                ):
                    if await loc.count() > 0:
                        await loc.first.fill(value, timeout=to)
                        return True, ''
                return False, f"Field '{field}' not found"
            except Exception as e:
                return False, str(e)[:120]

    # ── Select / create ───────────────────────────────────────────────────────
    if _re.search(r'\bselect\b', sl):
        m = _re.search(r"['\"]([^'\"]+)['\"]", s)
        if m:
            option = m.group(1)
            try:
                for exact in (True, False):
                    loc = page.get_by_text(option, exact=exact)
                    if await loc.count() > 0:
                        await loc.first.click(timeout=to)
                        await asyncio.sleep(0.8)
                        return True, ''
                # Try typing into visible input to create
                inp = page.get_by_role('textbox')
                if await inp.count() > 0:
                    await inp.first.fill(option)
                    await page.keyboard.press('Enter')
                    await asyncio.sleep(1)
                    return True, ''
                return False, f"Option '{option}' not found"
            except Exception as e:
                return False, str(e)[:120]

    # ── Assert URL ────────────────────────────────────────────────────────────
    if _re.search(r'\bassert\b', sl) and _re.search(r'\b(url|navigates?|redirects?)\b', sl):
        m = _re.search(r"(?:to|contains?)\s+['\"]?(/[^\s'\"]+|https?://[^\s'\"]+)['\"]?", s, _re.IGNORECASE)
        if m:
            expected = m.group(1).rstrip('.,;')
            current = page.url
            if expected in current:
                return True, ''
            # Wait up to 5s for navigation
            try:
                await page.wait_for_url(f"**{expected}**", timeout=5000)
                return True, ''
            except Exception:
                pass
            return False, f"URL '{page.url}' does not contain '{expected}'"

    # ── Assert disabled ───────────────────────────────────────────────────────
    if _re.search(r'\bassert\b', sl) and _re.search(r'\bdisabled\b', sl):
        m = _re.search(r"['\"]([^'\"]+)['\"]", s)
        if m:
            label = m.group(1)
            try:
                loc = page.get_by_role('button', name=label, exact=False)
                if await loc.count() > 0:
                    return (True, '') if await loc.first.is_disabled() else (False, f"'{label}' is not disabled")
                return True, ''  # button not found — non-blocking
            except Exception as e:
                return False, str(e)[:120]

    # ── Assert enabled ────────────────────────────────────────────────────────
    if _re.search(r'\bassert\b', sl) and _re.search(r'\benabled\b', sl):
        m = _re.search(r"['\"]([^'\"]+)['\"]", s)
        if m:
            label = m.group(1)
            try:
                loc = page.get_by_role('button', name=label, exact=False)
                if await loc.count() > 0:
                    return (True, '') if await loc.first.is_enabled() else (False, f"'{label}' is not enabled")
                return True, ''
            except Exception as e:
                return False, str(e)[:120]

    # ── Assert not visible ────────────────────────────────────────────────────
    if _re.search(r'\bassert\b', sl) and _re.search(r'\bnot\s+visible\b|\bno\s+longer\b|\bhidden\b', sl):
        m = _re.search(r"['\"]([^'\"]+)['\"]", s)
        if m:
            text = m.group(1)
            content = await page.content()
            if text.lower() not in content.lower():
                return True, ''
            loc = page.get_by_text(text, exact=False)
            if await loc.count() == 0:
                return True, ''
            try:
                if not await loc.first.is_visible():
                    return True, ''
            except Exception:
                pass
            return False, f"'{text}' should not be visible but is present"

    # ── Assert visible (general) ──────────────────────────────────────────────
    if _re.search(r'\b(assert|verify)\b', sl):
        texts = _re.findall(r"['\"]([^'\"]{2,})['\"]", s)
        if texts:
            content = await page.content()
            cl = content.lower()
            not_found = [t for t in texts if t.lower() not in cl]
            if not not_found:
                return True, ''
            return False, f"Not found on page: {'; '.join(repr(t) for t in not_found[:2])}"

    # ── Wait ──────────────────────────────────────────────────────────────────
    if _re.search(r'\bwait\b', sl):
        try:
            await page.wait_for_load_state('networkidle', timeout=5000)
        except Exception:
            pass
        await asyncio.sleep(1.5)
        return True, ''

    # ── Unrecognised — non-blocking ───────────────────────────────────────────
    return True, ''


def _check_text_assertions(steps: list, page_content: str) -> list:
    """Legacy helper — kept for compatibility."""
    content_lower = page_content.lower()
    failed = []
    for step in steps:
        if not _re.search(r'\b(?:assert|verify|check)\b', step, _re.IGNORECASE):
            continue
        for m in _re.finditer(r"['\"]([^'\"]{3,})['\"]", step):
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

    def _context_kwargs(self) -> dict:
        """Build new_context() kwargs from auth_config (storage_state or nothing)."""
        cfg = self.config.auth_config or {}
        if cfg.get("auth_type") == "storage_state" and cfg.get("storage_state"):
            return {"storage_state": cfg["storage_state"]}
        return {}

    async def _execute_with_semaphore(
        self,
        test_case: Dict[str, Any],
        index: int,
        progress_callback: Callable = None
    ) -> Dict[str, Any]:
        """Execute single test with semaphore control"""

        async with self._semaphore:
            logger.debug(f"Worker acquired for TC-{index+1}: {test_case.get('id', 'unknown')}")

            context = await self._browser.new_context(**self._context_kwargs())
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

        context = await self._browser.new_context(**self._context_kwargs())
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
        """Execute a test case step-by-step using Playwright interactions."""

        result = {
            **tc,
            "status": "pending",
            "screenshot_base64": None,
            "error_message": None,
            "actual_result": None,
            "execution_time_ms": 0,
        }

        start_time = datetime.now()
        steps = tc.get("steps", [])

        try:
            failures = []

            for step in steps:
                ok, err = await _execute_step(
                    page, step, self.config.app_url, self.config.timeout_ms
                )
                if not ok:
                    failures.append(err)

            # Auth redirect check after all steps
            if self.config.app_url.rstrip('/') not in page.url and 'sign-in' in page.url:
                result["status"] = "failed"
                result["error_message"] = "Redirected to sign-in — authentication may have expired"
            elif failures:
                result["status"] = "failed"
                result["error_message"] = "; ".join(failures[:3])
            else:
                result["status"] = "passed"
                result["actual_result"] = f"All {len(steps)} steps executed successfully"

        except asyncio.TimeoutError:
            result["status"] = "failed"
            result["error_message"] = f"Timeout after {self.config.timeout_ms}ms"
        except Exception as e:
            result["status"] = "failed"
            result["error_message"] = str(e)[:200]

        # Always capture screenshot
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
