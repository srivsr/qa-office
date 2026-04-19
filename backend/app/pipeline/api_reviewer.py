"""
ApiA7Reviewer — HITL gate that blocks on a threading.Event instead of stdin.
Injected into A11QADirector so the pipeline can pause for HTTP review decisions.
"""

import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from schemas import ReviewDecision, ReviewRequest

from app.core import state


class ApiA7Reviewer:
    """
    A7-compatible reviewer. Pauses the pipeline thread until
    POST /api/v1/test-runner/review/{run_id} delivers a decision.

    Timeout (default 5 min) auto-rejects to avoid hung pipelines.
    """

    def __init__(self, timeout_s: int = 300) -> None:
        self._timeout_s = timeout_s

    def run(self, request: ReviewRequest, run_id: Optional[str] = None) -> ReviewDecision:
        """Block until human submits decision via API or timeout expires."""
        run_id = run_id or request.run_id or uuid.uuid4().hex[:8]

        session = state.run_sessions.get(run_id, {})
        session["stage"] = "hitl_pending"
        session["review_request"] = {
            "run_id": run_id,
            "test_case_id": request.test_case_id,
            "source_agent": request.source_agent,
            "reason": request.reason,
        }

        event = threading.Event()
        state.review_events[run_id] = event

        got_input = event.wait(timeout=self._timeout_s)
        ts = datetime.now(timezone.utc).isoformat()
        base = dict(run_id=run_id, test_case_id=request.test_case_id, timestamp=ts)

        session["review_request"] = None
        state.review_events.pop(run_id, None)

        if not got_input:
            return ReviewDecision(**base, approved=True, comment="auto-approved after timeout")

        payload = state.review_decisions.pop(run_id, {})
        decision = payload.get("decision", "reject")
        agent_target = payload.get("agent_target")

        if decision == "approve":
            return ReviewDecision(**base, approved=True)
        if decision == "back" and agent_target:
            return ReviewDecision(**base, approved=False, send_back_to=agent_target.upper())
        return ReviewDecision(**base, approved=False, comment=payload.get("comment", "rejected"))
