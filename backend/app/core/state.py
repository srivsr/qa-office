"""In-memory session store shared across the process."""

import threading
from typing import Any, Dict

# run_id → session dict with pipeline progress
run_sessions: Dict[str, Dict[str, Any]] = {}

# run_id → Event set when human submits review decision
review_events: Dict[str, threading.Event] = {}

# run_id → ReviewDecision payload (set by POST /review endpoint)
review_decisions: Dict[str, Dict[str, Any]] = {}
