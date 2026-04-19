"""
Browser tool — thin adapter over qa-os Playwright executor.
Agents never import qa-os directly; they go through this wrapper.
"""

import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Load parallel_executor directly by path to avoid the `app` package name
# collision between qa-office/backend/app/ and qa-os/backend/app/.
_EXECUTOR_FILE = (
    Path(__file__).parents[2] / "qa-os" / "backend" / "app" / "services" / "parallel_executor.py"
)
_execute_tests_v2 = None


def _get_executor():
    global _execute_tests_v2
    if _execute_tests_v2 is None:
        spec = importlib.util.spec_from_file_location("qa_os_parallel_executor", _EXECUTOR_FILE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _execute_tests_v2 = mod.execute_tests_v2
    return _execute_tests_v2


class BrowserTool:
    """
    Executes test steps via Playwright using qa-os subprocess runner.
    Isolates the rest of the system from direct Playwright / qa-os imports.
    """

    def __init__(self, settings) -> None:
        self._settings = settings

    async def execute(
        self,
        test_cases: List[Dict[str, Any]],
        app_url: str,
        progress_callback: Optional[Callable] = None,
        execution_mode: Optional[str] = None,
        openai_api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute test cases and return raw result dicts.

        Args:
            test_cases:      List of dicts with id, title, steps, route, ...
            app_url:         Target URL (never production)
            progress_callback: Optional(completed, total, test_id)
            execution_mode:  page_check | scriptless | scripted (overrides settings)
            openai_api_key:  Required for scriptless / scripted (overrides settings)

        Returns:
            List of result dicts — same order as input
        """
        execute_tests_v2 = _get_executor()

        resolved_mode = execution_mode or getattr(self._settings, "execution_mode", "page_check")
        resolved_openai_key = openai_api_key or getattr(self._settings, "openai_api_key", "")

        # Inject keys for subprocess runner
        if self._settings.clerk_secret_key:
            os.environ["CLERK_SECRET_KEY"] = self._settings.clerk_secret_key
        if resolved_openai_key:
            os.environ["OPENAI_API_KEY"] = resolved_openai_key

        import json as _json

        _state_path = Path(__file__).parents[1] / "auth_state.json"
        auth_config = None
        if _state_path.exists():
            logger.info("BrowserTool: using saved auth_state.json")
            state = _json.loads(_state_path.read_text())
            auth_config = {
                "enabled": True,
                "auth_type": "storage_state",
                "storage_state": state,
            }
        elif self._settings.app_auth_enabled:
            auth_config = {
                "enabled": True,
                "auth_type": self._settings.app_auth_type,
                "email": self._settings.app_username,
                "password": self._settings.app_password,
            }

        logger.info(
            "BrowserTool.execute",
            extra={
                "test_count": len(test_cases),
                "app_url": app_url,
                "execution_mode": resolved_mode,
                "auth_enabled": self._settings.app_auth_enabled,
            },
        )
        return await execute_tests_v2(
            test_cases=test_cases,
            app_url=app_url,
            headless=self._settings.headless,
            parallel=False,
            max_workers=1,
            auth_config=auth_config,
            execution_mode=resolved_mode,
        )
