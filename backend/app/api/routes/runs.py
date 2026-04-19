"""
QA Office test-runner routes.

POST   /api/v1/test-runner/run              Start a run (upload or generate mode)
GET    /api/v1/test-runner/status/{run_id}  Poll run progress
GET    /api/v1/test-runner/report/{run_id}  Fetch A8 HTML report
POST   /api/v1/test-runner/review/{run_id}  Submit HITL decision
GET    /api/v1/test-runner/saved-runs       List recent runs
GET    /api/v1/test-runner/download/{run_id}  Download Excel report
GET    /api/v1/test-runner/test-cases/{run_id}
GET    /api/v1/test-runner/results/{run_id}
POST   /api/v1/test-runner/rerun/{run_id}
"""

import io
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.core import state
from app.pipeline import runner
from config.settings import settings as _settings

router = APIRouter(prefix="/test-runner", tags=["test-runner"])

_QA_ROOT = Path(__file__).parents[5]          # apps/qa-office/
UPLOADS_DIR = _QA_ROOT / "runs" / "uploads"


# ── Request / Response models ─────────────────────────────────────────────────


class RunResponse(BaseModel):
    """Returned immediately after POST /run."""
    run_id: str
    status: str
    message: str
    total_requirements: int = 0
    total_test_cases: int = 0
    download_url: Optional[str] = None


class StatusResponse(BaseModel):
    """Current pipeline state."""
    run_id: str
    status: str
    stage: str
    sub_stage: Optional[str] = None
    message: Optional[str] = None
    total_requirements: int = 0
    total_test_cases: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: Optional[str] = None
    paused_count: int = 0
    review_request: Optional[Dict[str, Any]] = None
    download_url: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None


class ReviewRequest(BaseModel):
    """HITL decision payload."""
    decision: str = Field(..., description="approve | reject | back")
    agent_target: Optional[str] = Field(None, description="A2 | A5 | A6 | A12 (for 'back' decision)")
    comment: Optional[str] = None


class SavedRun(BaseModel):
    id: str
    name: str
    environment: str
    status: str
    started_at: Optional[str]
    finished_at: Optional[str]
    summary: Dict[str, Any]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _session_or_404(run_id: str) -> Dict[str, Any]:
    session = state.run_sessions.get(run_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
    return session


def _stage_to_status(stage: str) -> str:
    """Map internal stage to frontend-compatible status string."""
    return {
        "queued": "started",
        "preparing": "started",
        "generating": "generating",
        "running": "executing",
        "hitl_pending": "hitl_pending",
        "complete": "completed",
        "error": "error",
    }.get(stage, stage)


def _build_summary(session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if session["stage"] != "complete":
        return None
    total = session["total"]
    passed = session["passed"]
    return {
        "total": total,
        "passed": passed,
        "failed": session["failed"],
        "pass_rate": f"{(passed / total * 100):.1f}%" if total else "N/A",
        "paused_count": session.get("paused_count", 0),
        "patterns": session.get("patterns", []),
        "alerts": session.get("alerts", []),
    }


# ── POST /run ─────────────────────────────────────────────────────────────────


@router.post("/run", response_model=RunResponse, status_code=202)
async def start_run(
    background_tasks: BackgroundTasks,
    app_url: str = Form(...),
    app_name: str = Form(default="Application"),
    mode: str = Form(default="upload", description="upload | generate"),
    requirement_text: Optional[str] = Form(None),
    auth_enabled: bool = Form(default=False),
    auth_type: str = Form(default="clerk"),
    auth_email: Optional[str] = Form(None),
    auth_password: Optional[str] = Form(None),
    parallel_execution: bool = Form(default=True),
    max_workers: int = Form(default=4, ge=1, le=10),
    capture_screenshots: bool = Form(default=True),
    input_mode: Optional[str] = Form(None),  # alias from frontend
    requirements_text: Optional[str] = Form(None),  # alias from frontend
    execution_mode: str = Form(default="page_check", description="page_check | scriptless | scripted"),
    openai_api_key: Optional[str] = Form(None, description="Required for scriptless/scripted modes"),
    file: Optional[UploadFile] = File(None),
):
    """
    Start a QA run.

    - **mode=upload**: supply a .xlsx/.csv/.txt file with existing test cases.
    - **mode=generate**: supply `requirement_text` — A0 generates test cases via Claude.

    Returns run_id immediately; poll /status/{run_id} for progress.
    """
    # Normalise aliases from frontend
    effective_mode = input_mode or mode
    if effective_mode == "existing":
        effective_mode = "upload"
    effective_text = requirement_text or requirements_text

    run_id = f"run-{uuid.uuid4().hex[:8]}"

    # Normalise execution mode — map legacy frontend values, fall back to page_check
    _mode_aliases = {
        "hybrid": "page_check",
        "script_only": "page_check",
        "llm_assisted": "scriptless",
    }
    execution_mode = _mode_aliases.get(execution_mode, execution_mode)
    if execution_mode not in ("page_check", "scriptless", "scripted"):
        execution_mode = "page_check"

    # Validate app_url is a proper HTTP/HTTPS URL
    if not re.match(r"^https?://[^\s/$.?#].[^\s]*$", app_url or ""):
        raise HTTPException(status_code=400, detail="app_url must be a valid http/https URL")

    resolved_key = openai_api_key or _settings.openai_api_key
    if execution_mode in ("scriptless", "scripted") and not resolved_key:
        raise HTTPException(
            status_code=400,
            detail=f"openai_api_key is required for {execution_mode} mode. "
                   f"Select Page Check mode to run without an OpenAI key."
        )

    params: Dict[str, Any] = {
        "app_url": app_url,
        "app_name": app_name,
        "mode": effective_mode,
        "auth_enabled": auth_enabled,
        "auth_type": auth_type,
        "auth_email": auth_email,
        "auth_password": auth_password,
        "parallel": parallel_execution,
        "max_workers": max_workers,
        "capture_screenshots": capture_screenshots,
        "execution_mode": execution_mode,
        "openai_api_key": resolved_key or "",
    }

    if effective_mode == "upload":
        if not file:
            raise HTTPException(status_code=400, detail="file is required for upload mode")
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^\w.\-]", "_", file.filename or "upload")
        upload_path = UPLOADS_DIR / f"{run_id}_{safe_name}"
        upload_path.write_bytes(await file.read())
        params["upload_path"] = str(upload_path)
    else:
        if not effective_text or not effective_text.strip():
            raise HTTPException(status_code=400, detail="requirement_text is required for generate mode")
        params["requirement_text"] = effective_text.strip()

    runner.submit_run(run_id, params)

    return RunResponse(
        run_id=run_id,
        status="started",
        message=f"Run started ({effective_mode} mode). Poll /status/{run_id} for progress.",
        download_url=f"/api/v1/test-runner/download/{run_id}",
    )


# ── GET /status/{run_id} ──────────────────────────────────────────────────────


@router.get("/status/{run_id}", response_model=StatusResponse)
async def get_status(run_id: str):
    """
    Poll the current pipeline stage and pass/fail counts.

    Stages: queued → preparing → generating → running → hitl_pending → complete | error
    """
    session = _session_or_404(run_id)
    stage = session["stage"]
    status = _stage_to_status(stage)
    summary = _build_summary(session)

    return StatusResponse(
        run_id=run_id,
        status=status,
        stage=stage,
        sub_stage=session.get("sub_stage"),
        message=session.get("error") if stage == "error" else None,
        total_requirements=session.get("total", 0),
        total_test_cases=session.get("total", 0),
        passed=session.get("passed", 0),
        failed=session.get("failed", 0),
        pass_rate=f"{session['passed'] / session['total'] * 100:.1f}%" if session.get("total") else None,
        paused_count=session.get("paused_count", 0),
        review_request=session.get("review_request"),
        download_url=f"/api/v1/test-runner/download/{run_id}" if stage == "complete" else None,
        summary=summary,
    )


# ── GET /report/{run_id} ──────────────────────────────────────────────────────


@router.get("/report/{run_id}", response_class=HTMLResponse)
async def get_report(run_id: str):
    """
    Return the A8 HTML report content for a completed run.
    Returns 404 if run is not yet complete or report file is missing.
    """
    session = _session_or_404(run_id)
    if session["stage"] != "complete":
        raise HTTPException(status_code=404, detail="Report not ready — run not complete")

    html_path = session.get("html_path")
    if not html_path or not Path(html_path).exists():
        raise HTTPException(status_code=404, detail="HTML report file not found")

    return HTMLResponse(content=Path(html_path).read_text(encoding="utf-8"))


# ── POST /review/{run_id} ─────────────────────────────────────────────────────


@router.post("/review/{run_id}")
async def submit_review(run_id: str, body: ReviewRequest):
    """
    Submit a HITL decision for a run paused at an A7 review gate.

    - **approve**: continue pipeline
    - **reject**: skip this test case
    - **back**: re-run the agent named in `agent_target` (A2 | A5 | A6 | A12)
    """
    session = _session_or_404(run_id)

    if session["stage"] != "hitl_pending":
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id!r} is not waiting for review (stage={session['stage']})"
        )

    valid_decisions = {"approve", "reject", "back"}
    if body.decision not in valid_decisions:
        raise HTTPException(status_code=400, detail=f"decision must be one of {valid_decisions}")

    if body.decision == "back" and not body.agent_target:
        raise HTTPException(status_code=400, detail="agent_target required when decision='back'")

    state.review_decisions[run_id] = {
        "decision": body.decision,
        "agent_target": body.agent_target,
        "comment": body.comment,
    }

    event = state.review_events.get(run_id)
    if event:
        event.set()

    return {"run_id": run_id, "status": "decision_recorded", "decision": body.decision}


# ── GET /saved-runs ───────────────────────────────────────────────────────────


@router.get("/saved-runs")
async def list_saved_runs():
    """
    List recent runs with status, pass/fail counts, and timestamps.
    Returns newest first, capped at 50.
    """
    runs = sorted(
        state.run_sessions.values(),
        key=lambda s: s.get("created_at", 0),
        reverse=True,
    )[:50]

    return {
        "total": len(runs),
        "runs": [
            {
                "id": s["run_id"],
                "name": s.get("app_name", "Unknown"),
                "environment": s.get("app_url", ""),
                "status": _stage_to_status(s["stage"]),
                "started_at": _epoch_to_iso(s.get("created_at")),
                "finished_at": _epoch_to_iso(s.get("finished_at")),
                "summary": {
                    "total_test_cases": s.get("total", 0),
                    "app_url": s.get("app_url", ""),
                    "passed": s.get("passed", 0),
                    "failed": s.get("failed", 0),
                    "pass_rate": f"{s['passed'] / s['total'] * 100:.1f}%" if s.get("total") else "N/A",
                },
            }
            for s in runs
        ],
    }


# ── GET /download/{run_id} ────────────────────────────────────────────────────


@router.get("/download/{run_id}")
async def download_report(run_id: str):
    """Download the A8 Excel report for a completed run."""
    session = _session_or_404(run_id)

    if session["stage"] != "complete":
        raise HTTPException(status_code=404, detail="Report not ready — run not complete")

    excel_path = session.get("excel_path")
    if not excel_path or not Path(excel_path).exists():
        raise HTTPException(status_code=404, detail="Excel report file not found")

    safe_name = re.sub(r"[^\w\-]", "_", session.get("app_name", "results"))
    filename = f"{safe_name}_{run_id}_results.xlsx"

    return StreamingResponse(
        io.BytesIO(Path(excel_path).read_bytes()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── GET /test-cases/{run_id} ──────────────────────────────────────────────────


@router.get("/test-cases/{run_id}")
async def get_test_cases(run_id: str):
    """
    Return test cases for a run.
    Available after the pipeline has ingested/generated them.
    """
    session = _session_or_404(run_id)
    return {
        "run_id": run_id,
        "total_test_cases": session.get("total", 0),
        "test_cases": session.get("test_cases", []),
    }


# ── GET /results/{run_id} ─────────────────────────────────────────────────────


@router.get("/results/{run_id}")
async def get_results(run_id: str):
    """Return execution results for a completed run."""
    session = _session_or_404(run_id)
    return {
        "run_id": run_id,
        "total_results": session.get("total", 0),
        "summary": _build_summary(session),
        "results": session.get("results", []),
    }


# ── POST /rerun/{run_id} ──────────────────────────────────────────────────────


@router.post("/rerun/{run_id}", response_model=RunResponse, status_code=202)
async def rerun(
    run_id: str,
    background_tasks: BackgroundTasks,
    app_url: Optional[str] = Form(None),
    parallel: bool = Form(default=True),
    max_workers: int = Form(default=4, ge=1, le=10),
    auth_enabled: bool = Form(default=False),
    auth_type: str = Form(default="clerk"),
    auth_email: Optional[str] = Form(None),
    auth_password: Optional[str] = Form(None),
):
    """
    Re-run a previously completed run using the same input file.
    Skips A0 generation — reuses the original upload or generated xlsx.
    """
    original = _session_or_404(run_id)

    original_excel = original.get("excel_path") or original.get("upload_path")
    if not original_excel or not Path(original_excel).exists():
        raise HTTPException(status_code=404, detail="Original input file not found for re-run")

    new_run_id = f"rerun-{uuid.uuid4().hex[:8]}"
    params: Dict[str, Any] = {
        "app_url": app_url or original["app_url"],
        "app_name": original.get("app_name", "Application"),
        "mode": "upload",
        "upload_path": original_excel,
        "parallel": parallel,
        "max_workers": max_workers,
        "auth_enabled": auth_enabled,
        "auth_type": auth_type,
        "auth_email": auth_email,
        "auth_password": auth_password,
    }
    runner.submit_run(new_run_id, params)

    return RunResponse(
        run_id=new_run_id,
        status="started",
        message=f"Re-run of {run_id} started.",
        download_url=f"/api/v1/test-runner/download/{new_run_id}",
    )


# ── Utility ───────────────────────────────────────────────────────────────────


def _epoch_to_iso(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
