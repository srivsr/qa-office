"""
A7 Reviewer — Human-in-the-Loop gate. Blocking. No LLM.
One job: escalate uncertain/irreversible agent results to a human,
record the decision in A9, and return routing instructions.

Trigger conditions (enforced by A11 Director via director_service.should_invoke_a7):
  - Any agent confidence < review_threshold (PAUSE status)
  - A6 applied a repair (review_required=True)
  - A5 diagnosed GOAL_DRIFT or SCOPE_CREEP

Timeout: settings.a7_timeout_s (default 5 min). Expired → rejected, not crash.
Write-access: every human decision written to A9 as ground truth.
"""

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from agents.a09_memory_keeper import A9MemoryKeeper
from config.settings import settings as default_settings
from schemas import MemoryWrite, ReviewDecision, ReviewRequest

logger = logging.getLogger(__name__)

_VALID_SEND_BACK = {"A2", "A5", "A6", "A12"}
_PROMPT = (
    "\nrun_id={run_id}  tc={tc_id}  from={agent}\n"
    "Reason: {reason}\n"
    "Options: approve | reject | back:A2 | back:A5 | back:A6 | back:A12\n"
    "Choice: "
)


class A7Reviewer:
    """
    Blocking HITL gate — waits for human decision before pipeline continues.

    Injectable input_fn for testing (default: real stdin with timeout).
    Injectable memory for testing (default: real A9MemoryKeeper).

    Input:  ReviewRequest
    Output: ReviewDecision
    """

    def __init__(
        self,
        settings=None,
        input_fn: Optional[Callable[[str], Optional[str]]] = None,
        memory: Optional[A9MemoryKeeper] = None,
    ) -> None:
        self._settings = settings or default_settings
        self._input_fn = input_fn
        self._memory = memory or A9MemoryKeeper()

    def run(
        self, request: ReviewRequest, run_id: Optional[str] = None
    ) -> ReviewDecision:
        run_id = run_id or request.run_id or uuid.uuid4().hex[:8]
        logger.warning(
            "A7 HITL gate — awaiting human decision",
            extra={"run_id": run_id, "source_agent": request.source_agent},
        )

        raw = self._ask(request)
        decision = self._parse(raw, request, run_id)

        self._memory.write(
            MemoryWrite(
                source_agent="A7",
                record_type="human_decision",
                run_id=run_id,
                test_case_id=request.test_case_id,
                payload={
                    "decision": "approved" if decision.approved else "rejected",
                    "reason": decision.comment or request.reason,
                    "decided_by": decision.decided_by,
                },
            )
        )

        logger.info(
            "A7 decision: approved=%s send_back_to=%s",
            decision.approved,
            decision.send_back_to,
            extra={"run_id": run_id},
        )
        return decision

    # ── private helpers ────────────────────────────────────────────────────────

    def _ask(self, request: ReviewRequest) -> Optional[str]:
        prompt = _PROMPT.format(
            run_id=request.run_id,
            tc_id=request.test_case_id,
            agent=request.source_agent,
            reason=request.reason[:120],
        )
        if self._input_fn:
            return self._input_fn(prompt)
        return _timed_input(prompt, self._settings.a7_timeout_s)

    def _parse(
        self, raw: Optional[str], request: ReviewRequest, run_id: str
    ) -> ReviewDecision:
        ts = datetime.now(timezone.utc).isoformat()
        base = dict(
            run_id=run_id,
            test_case_id=request.test_case_id,
            timestamp=ts,
        )
        if not raw:
            logger.warning("A7 timeout — auto-rejecting %s", request.test_case_id)
            return ReviewDecision(**base, approved=False, comment="timeout")

        token = raw.strip().lower()
        if token == "approve":
            return ReviewDecision(**base, approved=True)
        if token == "reject":
            return ReviewDecision(**base, approved=False, comment="human rejected")
        if token.startswith("back:"):
            target = token[5:].upper()
            if target in _VALID_SEND_BACK:
                return ReviewDecision(**base, approved=False, send_back_to=target)
        # Unknown input → reject
        logger.warning("A7 unknown input %r — rejecting", raw)
        return ReviewDecision(**base, approved=False, comment=f"unknown input: {raw!r}")


# ── stdin helper ───────────────────────────────────────────────────────────────


def _timed_input(prompt: str, timeout_s: int) -> Optional[str]:
    """Read one line from stdin with a timeout. Returns None on timeout/EOF."""
    result: list = [None]
    event = threading.Event()

    def _read() -> None:
        try:
            result[0] = input(prompt)
        except EOFError:
            result[0] = ""
        finally:
            event.set()

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    event.wait(timeout=timeout_s)
    return result[0]
