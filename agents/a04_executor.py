"""
A4 Executor — thin orchestrator.
One job: run list[TestCase] against the target app → AgentResult(artifacts={"results": [...]}).
All execution and retry logic lives in services/execution_service.py.
Browser I/O goes through tools/browser_tool.py.
POM-first: uses A14 page object locators when available; falls back to live A3 discovery.

Guarantees:
- Never runs against production (app_url required, validated non-empty)
- Propagates run_id for full trace across pipeline
"""

import asyncio
import logging
import time
import uuid
from typing import List, Optional

from agents.a09_memory_keeper import A9MemoryKeeper
from config.settings import settings as default_settings
from schemas import AgentResult, MemoryWrite, TestCase
from services import execution_service
from tools.browser_tool import BrowserTool

logger = logging.getLogger(__name__)
_memory = A9MemoryKeeper()


class A4Executor:
    """
    Executes test cases via Playwright (through BrowserTool → qa-os).

    Input:  list[TestCase], app_url, run_id
    Output: AgentResult
              status="success"|"error"
              artifacts={"results": list[ExecutionResult]}
              metrics={"total": int, "passed": int, "duration_ms": int}

    Phase 1: deterministic page execution (no LLM).
    Phase 2: step-level execution delegated to A2 IntentInterpreter.
    """

    def __init__(self, settings=None) -> None:
        self._settings = settings or default_settings
        self._browser = BrowserTool(self._settings)

    def run(
        self,
        test_cases: List[TestCase],
        app_url: str,
        run_id: Optional[str] = None,
        output_dir: str = "runs",
        pom_result=None,  # POMResult from A14, optional
        execution_mode: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        auth_email: Optional[str] = None,
        auth_password: Optional[str] = None,
        auth_type: Optional[str] = None,
    ) -> AgentResult:
        """
        Execute all test cases synchronously (wraps async loop).
        Call from sync context only (CLI / run_phaseX.py).
        """
        if not app_url:
            return AgentResult(
                status="error",
                confidence=1.0,
                error_message="app_url is required — never run against production",
                retryable=False,
            )

        run_id = run_id or uuid.uuid4().hex[:8]
        # Build url→PageMap index for POM-first selector injection
        pom_index = {}
        if pom_result:
            try:
                for pm in pom_result.get("page_maps", []):
                    pom_index[pm.get("url", "")] = pm
            except Exception:
                pass

        logger.info(
            "A4 start",
            extra={"run_id": run_id, "agent": "A4Executor", "count": len(test_cases),
                   "pom_pages": len(pom_index)},
        )
        t0 = time.time()

        results = asyncio.run(self._execute_all(test_cases, app_url, run_id, execution_mode, openai_api_key, auth_email, auth_password, auth_type))
        ms = int((time.time() - t0) * 1000)
        passed = sum(1 for r in results if r.status == "passed")

        logger.info(
            "A4 complete",
            extra={
                "run_id": run_id,
                "passed": passed,
                "total": len(results),
                "duration_ms": ms,
            },
        )
        for r in results:
            _memory.write(
                MemoryWrite(
                    source_agent="A4",
                    record_type="run",
                    run_id=run_id,
                    test_case_id=r.test_case_id,
                    payload={
                        "status": r.status,
                        "retry_count": r.retry_count,
                        "duration_ms": r.duration_ms,
                    },
                )
            )
        return AgentResult(
            status="success",
            confidence=1.0,
            artifacts={"results": results},
            metrics={"total": len(results), "passed": passed, "duration_ms": ms},
        )

    async def _execute_all(self, test_cases, app_url, run_id,
                           execution_mode=None, openai_api_key=None,
                           auth_email=None, auth_password=None, auth_type=None):
        results = []
        for tc in test_cases:
            r = await execution_service.execute_with_retry(
                tc, app_url, run_id, self._settings, self._browser,
                execution_mode=execution_mode,
                openai_api_key=openai_api_key,
                auth_email=auth_email,
                auth_password=auth_password,
                auth_type=auth_type,
            )
            results.append(r)
        return results
