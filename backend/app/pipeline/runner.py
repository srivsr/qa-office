"""
Pipeline runner — submits A11QADirector to a thread pool.
Handles upload (existing test cases) and generate (A0 → xlsx) modes.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

import openpyxl

from app.core import state
from app.pipeline.api_reviewer import ApiA7Reviewer
from schemas import QAMission, TestCase

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="qa-pipeline")
_shutdown = threading.Event()

_QA_ROOT = Path(__file__).parents[3]          # apps/qa-office/
RUNS_DIR = _QA_ROOT / "runs"
UPLOADS_DIR = _QA_ROOT / "runs" / "uploads"


def shutdown() -> None:
    """Signal running pipelines to stop and drain the executor. Called on app shutdown."""
    _shutdown.set()
    _executor.shutdown(wait=False, cancel_futures=True)


def submit_run(run_id: str, params: Dict[str, Any]) -> None:
    """Initialise session and submit pipeline to thread pool. Returns immediately."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    state.run_sessions[run_id] = {
        "run_id": run_id,
        "stage": "queued",
        "app_url": params.get("app_url"),
        "app_name": params.get("app_name"),
        "passed": 0,
        "failed": 0,
        "total": 0,
        "pass_rate": 0.0,
        "paused_count": 0,
        "html_path": None,
        "excel_path": None,
        "error": None,
        "review_request": None,
        "patterns": [],
        "alerts": [],
        "created_at": time.time(),
    }
    _executor.submit(_run_pipeline, run_id, params)


def _run_pipeline(run_id: str, params: Dict[str, Any]) -> None:
    """Executed in thread pool. Updates session state throughout."""
    if _shutdown.is_set():
        return
    session = state.run_sessions[run_id]
    try:
        session["stage"] = "preparing"
        excel_path = _prepare_input(run_id, params)

        session["stage"] = "running"
        output_dir = str(RUNS_DIR)  # A11 appends run_id internally → runs/{run_id}/

        from agents.a11_qa_director import A11QADirector

        def _on_stage(sub: str) -> None:
            session["sub_stage"] = sub

        reviewer = ApiA7Reviewer(timeout_s=30)
        mission = QAMission(
            excel_path=excel_path,
            app_url=params["app_url"],
            app_name=params.get("app_name", ""),
            output_dir=output_dir,
            execution_mode=params.get("execution_mode", "page_check"),
            openai_api_key=params.get("openai_api_key", ""),
            auth_enabled=params.get("auth_enabled", False),
            auth_email=params.get("auth_email") or "",
            auth_password=params.get("auth_password") or "",
            auth_type=params.get("auth_type", "clerk"),
        )
        result = A11QADirector(agents={"A7": reviewer}).run(
            mission, run_id=run_id, stage_cb=_on_stage
        )

        if result.status == "error":
            session["stage"] = "error"
            session["error"] = result.error_message
            return

        mr = result.artifacts.get("mission_result")
        if mr is None:
            session["stage"] = "error"
            session["error"] = "Pipeline returned no mission_result"
            return

        mr_dict = mr.model_dump() if hasattr(mr, "model_dump") else dict(mr)
        session.update({
            "stage": "complete",
            "passed": mr_dict.get("passed", 0),
            "failed": mr_dict.get("failed", 0),
            "total": mr_dict.get("total", 0),
            "pass_rate": mr_dict.get("pass_rate", 0.0),
            "paused_count": mr_dict.get("paused_count", 0),
            "html_path": mr_dict.get("html_path"),
            "excel_path": mr_dict.get("excel_path_report"),
            "patterns": mr_dict.get("patterns", []),
            "alerts": [
                a.model_dump() if hasattr(a, "model_dump") else a
                for a in mr_dict.get("proactive_alerts", [])
            ],
        })

    except Exception as exc:
        logger.exception("Pipeline failed run_id=%s", run_id)
        session["stage"] = "error"
        session["error"] = str(exc)


def _prepare_input(run_id: str, params: Dict[str, Any]) -> str:
    """Return a file path A1 Ingestion can parse."""
    mode = params.get("mode", "upload")

    if mode == "upload":
        path = params.get("upload_path")
        if not path or not Path(path).exists():
            raise FileNotFoundError(f"Uploaded file not found: {path}")
        return path

    # generate mode — A0 → xlsx
    requirement_text = params.get("requirement_text", "").strip()
    if not requirement_text:
        raise ValueError("requirement_text is required for generate mode")

    test_cases = _generate_via_a0(requirement_text, run_id)
    return _write_test_cases_xlsx(test_cases, run_id)


def _generate_via_a0(requirement: str, run_id: str) -> List[TestCase]:
    """Call A0TestGenerator to turn plain-English description into TestCase objects."""
    from agents.a00_test_generator import A0TestGenerator

    session = state.run_sessions[run_id]
    session["stage"] = "generating"
    session["sub_stage"] = "generating"

    result = A0TestGenerator().run(
        requirement=requirement,
        module="Generated",
        count=7,
        run_id=run_id,
        app_url=session.get("app_url", ""),
        app_name=session.get("app_name", ""),
    )
    if result.status == "error":
        raise RuntimeError(f"A0 generation failed: {result.error_message}")

    test_cases = result.artifacts.get("test_cases", [])
    if not test_cases:
        note = result.artifacts.get("coverage_note", "") if result.artifacts else ""
        raise RuntimeError(
            f"A0 produced no test cases. "
            f"Confidence: {result.confidence:.2f}. "
            f"Reason: {note or 'LLM returned empty list — check prompt or increase max_tokens'}"
        )
    return test_cases


def _write_test_cases_xlsx(test_cases: List[TestCase], run_id: str) -> str:
    """Serialize TestCase list to xlsx A1 Ingestion can parse."""
    path = RUNS_DIR / f"{run_id}_generated.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Test Cases"
    ws.append(["Test Case ID", "Module", "Description", "Test Steps", "Expected Result", "Priority"])
    for tc in test_cases:
        ws.append([tc.id, tc.module, tc.description, "\n".join(tc.steps), tc.expected_result, tc.priority])
    wb.save(str(path))
    logger.info("Generated xlsx: %s (%d test cases)", path.name, len(test_cases))
    return str(path)
