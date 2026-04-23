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


@dataclass
class ExecutionConfig:
    """Configuration for test execution"""
    app_url: str
    headless: bool = True
    parallel: bool = False
    max_workers: int = 4
    timeout_ms: int = 30000
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

            await page.goto(url, wait_until='networkidle', timeout=self.config.timeout_ms)
            await asyncio.sleep(0.5)

            title = await page.title()
            content = await page.content()

            if len(content) > 500:
                result["status"] = "passed"
                result["actual_result"] = f"Page loaded: {title}"
            else:
                result["status"] = "failed"
                result["error_message"] = "Page content too short"

            if (result["status"] == "passed" and self.config.screenshot_on_pass) or \
               (result["status"] == "failed" and self.config.screenshot_on_fail):
                screenshot_bytes = await page.screenshot(full_page=False)
                result["screenshot_base64"] = base64.b64encode(screenshot_bytes).decode('utf-8')

        except asyncio.TimeoutError:
            result["status"] = "failed"
            result["error_message"] = f"Timeout loading page after {self.config.timeout_ms}ms"

        except Exception as e:
            result["status"] = "failed"
            result["error_message"] = str(e)

            try:
                screenshot_bytes = await page.screenshot(full_page=False)
                result["screenshot_base64"] = base64.b64encode(screenshot_bytes).decode('utf-8')
            except:
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
    execution_mode: str = "auto",  # auto | scriptless | scripted | page_check
    screenshot_dir: str = None,  # if set, save PNGs here instead of test_results/
) -> List[Dict[str, Any]]:
    """
    Execute tests using subprocess approach for Windows compatibility.

    Args:
        test_cases: List of test cases
        app_url: Application URL
        headless: Run headless browser
        parallel: Enable parallel execution
        max_workers: Number of parallel workers (default: 4)
        auth_config: Authentication configuration
        progress_callback: Optional callback(completed, total, current_id)

    Returns:
        List of results
    """
    if not test_cases:
        return []

    # Use data folder for temp files
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)

    session_id = uuid.uuid4().hex[:8]
    input_file = str(data_dir / f"test_input_{session_id}.json")
    output_file = str(data_dir / f"test_output_{session_id}.json")

    # Use caller-supplied screenshot_dir when provided (e.g. qa-office/runs/{run_id}/screenshots/)
    # otherwise fall back to qa-os/test_results/screenshots/{session_id}/
    if screenshot_dir:
        screenshot_dir = Path(screenshot_dir)
    else:
        test_results_dir = Path(__file__).parent.parent.parent.parent / "test_results"
        test_results_dir.mkdir(exist_ok=True)
        screenshot_dir = test_results_dir / "screenshots" / session_id
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    # Write test cases to input file
    # Include CLERK_SECRET_KEY for API-based auth (bypasses device verification)
    # Load .env file explicitly
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        from dotenv import load_dotenv
        load_dotenv(env_file)

    clerk_secret = os.environ.get('CLERK_SECRET_KEY', '')
    if clerk_secret:
        print(f"[EXEC] CLERK_SECRET_KEY found: {clerk_secret[:10]}...")
    else:
        print(f"[EXEC] WARNING: CLERK_SECRET_KEY not found in environment")

    openai_key = os.environ.get('OPENAI_API_KEY', '')

    # Resolve execution mode
    if execution_mode == "auto":
        resolved_mode = "scriptless" if openai_key else "page_check"
    else:
        resolved_mode = execution_mode

    scripts_dir = str(test_results_dir / "scripts" / session_id)

    with open(input_file, 'w', encoding='utf-8') as f:
        json.dump({
            'test_cases': test_cases,
            'app_url': app_url,
            'headless': headless,
            'parallel': parallel,
            'max_workers': max_workers,
            'auth': auth_config or {},
            'screenshot_dir': str(screenshot_dir),
            'clerk_secret_key': clerk_secret,
            'openai_api_key': openai_key,
            'execution_mode': resolved_mode,
            'scripts_dir': scripts_dir,
        }, f)

    # Path to runner script
    runner_script = Path(__file__).parent / "playwright_runner.py"

    try:
        python_exe = sys.executable
        logger.info(f"[EXEC] Starting Playwright subprocess: {len(test_cases)} tests")
        logger.info(f"[EXEC] Script: {runner_script}")
        _auth = auth_config or {}
        logger.info("[EXEC] Auth config: type=%s, email=%s", _auth.get("auth_type", "none"), _auth.get("email", ""))
        print(f"[EXEC] Starting Playwright subprocess: {len(test_cases)} tests")

        # Run subprocess in thread pool. Use get_running_loop() (get_event_loop() is
        # deprecated in 3.10+ and returns wrong loop inside a running coroutine).
        # Shield the future so a CancelledError on the outer task does not abort the
        # subprocess mid-run — we still wait for it to finish.
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [python_exe, str(runner_script), input_file, output_file],
                timeout=3600,
                capture_output=False
            )
        )
        try:
            result = await asyncio.shield(future)
        except asyncio.CancelledError:
            # Outer task was cancelled (e.g. uvicorn --reload). Wait for the
            # subprocess to finish so the output file is written, then return results.
            print("[EXEC] CancelledError caught — waiting for subprocess to finish...")
            result = await future

        print(f"[EXEC] Subprocess return code: {result.returncode}")

        if result.returncode != 0:
            logger.error(f"[EXEC] Subprocess failed with code {result.returncode}")
            return [
                {**tc, "status": "failed", "error_message": f"Subprocess error (code {result.returncode})"}
                for tc in test_cases
            ]

        # Read results
        if not os.path.exists(output_file):
            logger.error("[EXEC] Output file not found")
            return [
                {**tc, "status": "failed", "error_message": "Test output file not created"}
                for tc in test_cases
            ]

        with open(output_file, 'r', encoding='utf-8') as f:
            results = json.load(f)

        logger.info(f"[EXEC] Completed {len(results)} tests")
        return results

    except subprocess.TimeoutExpired:
        logger.error("[EXEC] Subprocess timed out")
        return [
            {**tc, "status": "failed", "error_message": "Test execution timed out (60 min)"}
            for tc in test_cases
        ]
    except Exception as e:
        logger.error(f"[EXEC] Error: {e}")
        return [
            {**tc, "status": "failed", "error_message": f"Execution error: {str(e)}"}
            for tc in test_cases
        ]
    finally:
        # Cleanup temp files
        for f in [input_file, output_file]:
            try:
                os.unlink(f)
            except:
                pass
