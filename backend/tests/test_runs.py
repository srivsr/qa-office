"""
Unit tests for /api/v1/test-runner/* endpoints.

All tests mock the pipeline runner and A11 so no real Playwright/Claude calls happen.
"""

import io
import time
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Patch heavy imports before app loads
import sys
sys.modules.setdefault("anthropic", MagicMock())

import main  # noqa: E402 — must come after sys.path setup in conftest
from app.core import state

client = TestClient(main.app)

# ── helpers ───────────────────────────────────────────────────────────────────


def _seed_session(run_id: str, stage: str = "complete", **overrides) -> Dict[str, Any]:
    session: Dict[str, Any] = {
        "run_id": run_id,
        "stage": stage,
        "app_url": "http://localhost:3000",
        "app_name": "TestApp",
        "passed": 8,
        "failed": 2,
        "total": 10,
        "pass_rate": 80.0,
        "paused_count": 0,
        "html_path": None,
        "excel_path": None,
        "error": None,
        "review_request": None,
        "patterns": [],
        "alerts": [],
        "created_at": time.time(),
    }
    session.update(overrides)
    state.run_sessions[run_id] = session
    return session


def _cleanup(run_id: str) -> None:
    state.run_sessions.pop(run_id, None)
    state.review_events.pop(run_id, None)
    state.review_decisions.pop(run_id, None)


# ── POST /run — upload mode ───────────────────────────────────────────────────


class TestStartRunUpload:
    def setup_method(self):
        self.run_ids = []

    def teardown_method(self):
        for rid in self.run_ids:
            _cleanup(rid)

    @patch("app.pipeline.runner.submit_run")
    def test_returns_202_with_run_id(self, mock_submit):
        """upload mode returns 202 and a run_id immediately."""
        fake_file = io.BytesIO(b"col1,col2\nval1,val2")
        resp = client.post(
            "/api/v1/test-runner/run",
            data={"app_url": "http://localhost:3000", "mode": "upload"},
            files={"file": ("test.csv", fake_file, "text/csv")},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "run_id" in body
        assert body["status"] == "started"
        self.run_ids.append(body["run_id"])

    @patch("app.pipeline.runner.submit_run")
    def test_download_url_in_response(self, mock_submit):
        """download_url points to the correct path."""
        fake_file = io.BytesIO(b"steps,expected_result\ndo it,done")
        resp = client.post(
            "/api/v1/test-runner/run",
            data={"app_url": "http://localhost:3000", "mode": "upload"},
            files={"file": ("tc.csv", fake_file, "text/csv")},
        )
        body = resp.json()
        run_id = body["run_id"]
        self.run_ids.append(run_id)
        assert body["download_url"] == f"/api/v1/test-runner/download/{run_id}"

    def test_upload_mode_without_file_returns_400(self):
        """Missing file in upload mode → 400."""
        resp = client.post(
            "/api/v1/test-runner/run",
            data={"app_url": "http://localhost:3000", "mode": "upload"},
        )
        assert resp.status_code == 400

    def test_missing_app_url_returns_422(self):
        """app_url is required — missing returns 422."""
        fake_file = io.BytesIO(b"data")
        resp = client.post(
            "/api/v1/test-runner/run",
            data={"mode": "upload"},
            files={"file": ("f.csv", fake_file, "text/csv")},
        )
        assert resp.status_code == 422


# ── POST /run — generate mode ─────────────────────────────────────────────────


class TestStartRunGenerate:
    def setup_method(self):
        self.run_ids = []

    def teardown_method(self):
        for rid in self.run_ids:
            _cleanup(rid)

    @patch("app.pipeline.runner.submit_run")
    def test_returns_202_with_run_id(self, mock_submit):
        """generate mode with requirement_text returns 202."""
        resp = client.post(
            "/api/v1/test-runner/run",
            data={
                "app_url": "http://localhost:3000",
                "mode": "generate",
                "requirement_text": "User can login with email and password",
            },
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "started"
        self.run_ids.append(body["run_id"])

    def test_generate_mode_without_text_returns_400(self):
        """generate mode missing requirement_text → 400."""
        resp = client.post(
            "/api/v1/test-runner/run",
            data={"app_url": "http://localhost:3000", "mode": "generate"},
        )
        assert resp.status_code == 400


# ── GET /status/{run_id} ──────────────────────────────────────────────────────


class TestGetStatus:
    def setup_method(self):
        self.run_id = f"run-{uuid.uuid4().hex[:8]}"

    def teardown_method(self):
        _cleanup(self.run_id)

    def test_unknown_run_returns_404(self):
        resp = client.get("/api/v1/test-runner/status/nonexistent-run")
        assert resp.status_code == 404

    def test_queued_run(self):
        _seed_session(self.run_id, stage="queued", total=0, passed=0, failed=0)
        resp = client.get(f"/api/v1/test-runner/status/{self.run_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "started"
        assert body["stage"] == "queued"

    def test_complete_run_has_summary(self):
        _seed_session(self.run_id, stage="complete")
        resp = client.get(f"/api/v1/test-runner/status/{self.run_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["summary"] is not None
        assert body["summary"]["total"] == 10

    def test_error_run_returns_message(self):
        _seed_session(self.run_id, stage="error", error="Playwright crashed")
        resp = client.get(f"/api/v1/test-runner/status/{self.run_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert "Playwright crashed" in body["message"]

    def test_hitl_pending_exposes_review_request(self):
        review_req = {"run_id": self.run_id, "test_case_id": "TC-001", "source_agent": "A5", "reason": "low conf"}
        _seed_session(self.run_id, stage="hitl_pending", review_request=review_req)
        resp = client.get(f"/api/v1/test-runner/status/{self.run_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["stage"] == "hitl_pending"
        assert body["review_request"]["test_case_id"] == "TC-001"


# ── GET /report/{run_id} ──────────────────────────────────────────────────────


class TestGetReport:
    def setup_method(self):
        self.run_id = f"run-{uuid.uuid4().hex[:8]}"

    def teardown_method(self):
        _cleanup(self.run_id)

    def test_not_complete_returns_404(self):
        _seed_session(self.run_id, stage="running")
        resp = client.get(f"/api/v1/test-runner/report/{self.run_id}")
        assert resp.status_code == 404

    def test_complete_no_html_path_returns_404(self):
        _seed_session(self.run_id, stage="complete", html_path=None)
        resp = client.get(f"/api/v1/test-runner/report/{self.run_id}")
        assert resp.status_code == 404

    def test_complete_with_html_path_returns_html(self, tmp_path):
        html_file = tmp_path / "report.html"
        html_file.write_text("<html><body>Report</body></html>")
        _seed_session(self.run_id, stage="complete", html_path=str(html_file))
        resp = client.get(f"/api/v1/test-runner/report/{self.run_id}")
        assert resp.status_code == 200
        assert "Report" in resp.text

    def test_unknown_run_returns_404(self):
        resp = client.get("/api/v1/test-runner/report/no-such-run")
        assert resp.status_code == 404


# ── POST /review/{run_id} ─────────────────────────────────────────────────────


class TestSubmitReview:
    def setup_method(self):
        self.run_id = f"run-{uuid.uuid4().hex[:8]}"

    def teardown_method(self):
        _cleanup(self.run_id)

    def test_review_on_non_pending_run_returns_409(self):
        _seed_session(self.run_id, stage="running")
        resp = client.post(
            f"/api/v1/test-runner/review/{self.run_id}",
            json={"decision": "approve"},
        )
        assert resp.status_code == 409

    def test_approve_sets_event_and_returns_200(self):
        import threading
        _seed_session(self.run_id, stage="hitl_pending")
        event = threading.Event()
        state.review_events[self.run_id] = event

        resp = client.post(
            f"/api/v1/test-runner/review/{self.run_id}",
            json={"decision": "approve"},
        )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "approve"
        assert event.is_set()

    def test_reject_decision_recorded(self):
        import threading
        _seed_session(self.run_id, stage="hitl_pending")
        state.review_events[self.run_id] = threading.Event()

        resp = client.post(
            f"/api/v1/test-runner/review/{self.run_id}",
            json={"decision": "reject", "comment": "wrong selector"},
        )
        assert resp.status_code == 200
        assert state.review_decisions[self.run_id]["decision"] == "reject"

    def test_back_without_agent_target_returns_400(self):
        _seed_session(self.run_id, stage="hitl_pending")
        resp = client.post(
            f"/api/v1/test-runner/review/{self.run_id}",
            json={"decision": "back"},
        )
        assert resp.status_code == 400

    def test_back_with_agent_target_accepted(self):
        import threading
        _seed_session(self.run_id, stage="hitl_pending")
        state.review_events[self.run_id] = threading.Event()

        resp = client.post(
            f"/api/v1/test-runner/review/{self.run_id}",
            json={"decision": "back", "agent_target": "A5"},
        )
        assert resp.status_code == 200
        assert state.review_decisions[self.run_id]["agent_target"] == "A5"

    def test_invalid_decision_returns_400(self):
        _seed_session(self.run_id, stage="hitl_pending")
        resp = client.post(
            f"/api/v1/test-runner/review/{self.run_id}",
            json={"decision": "maybe"},
        )
        assert resp.status_code == 400

    def test_unknown_run_returns_404(self):
        resp = client.post(
            "/api/v1/test-runner/review/no-such-run",
            json={"decision": "approve"},
        )
        assert resp.status_code == 404


# ── GET /saved-runs ───────────────────────────────────────────────────────────


class TestSavedRuns:
    def setup_method(self):
        self.run_ids = []

    def teardown_method(self):
        for rid in self.run_ids:
            _cleanup(rid)

    def test_empty_returns_zero_total(self):
        # Clear all sessions for a clean count
        existing = list(state.run_sessions.keys())
        saved = {k: state.run_sessions.pop(k) for k in existing}
        try:
            resp = client.get("/api/v1/test-runner/saved-runs")
            assert resp.status_code == 200
            assert resp.json()["total"] == 0
        finally:
            state.run_sessions.update(saved)

    def test_returns_recent_runs(self):
        r1 = f"run-{uuid.uuid4().hex[:8]}"
        r2 = f"run-{uuid.uuid4().hex[:8]}"
        self.run_ids.extend([r1, r2])
        _seed_session(r1, stage="complete")
        _seed_session(r2, stage="running")

        resp = client.get("/api/v1/test-runner/saved-runs")
        assert resp.status_code == 200
        ids = [r["id"] for r in resp.json()["runs"]]
        assert r1 in ids
        assert r2 in ids

    def test_run_summary_fields_present(self):
        rid = f"run-{uuid.uuid4().hex[:8]}"
        self.run_ids.append(rid)
        _seed_session(rid, stage="complete")

        resp = client.get("/api/v1/test-runner/saved-runs")
        run = next(r for r in resp.json()["runs"] if r["id"] == rid)
        assert "status" in run
        assert "summary" in run
        assert "passed" in run["summary"]


# ── GET /download/{run_id} ────────────────────────────────────────────────────


class TestDownload:
    def setup_method(self):
        self.run_id = f"run-{uuid.uuid4().hex[:8]}"

    def teardown_method(self):
        _cleanup(self.run_id)

    def test_not_complete_returns_404(self):
        _seed_session(self.run_id, stage="running")
        resp = client.get(f"/api/v1/test-runner/download/{self.run_id}")
        assert resp.status_code == 404

    def test_complete_with_excel_returns_file(self, tmp_path):
        xlsx = tmp_path / "report.xlsx"
        xlsx.write_bytes(b"PK fake xlsx content")
        _seed_session(self.run_id, stage="complete", excel_path=str(xlsx))
        resp = client.get(f"/api/v1/test-runner/download/{self.run_id}")
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers["content-type"]

    def test_complete_no_excel_path_returns_404(self):
        _seed_session(self.run_id, stage="complete", excel_path=None)
        resp = client.get(f"/api/v1/test-runner/download/{self.run_id}")
        assert resp.status_code == 404


# ── GET /test-cases and /results ──────────────────────────────────────────────


class TestTestCasesAndResults:
    def setup_method(self):
        self.run_id = f"run-{uuid.uuid4().hex[:8]}"

    def teardown_method(self):
        _cleanup(self.run_id)

    def test_test_cases_unknown_run_returns_404(self):
        resp = client.get("/api/v1/test-runner/test-cases/unknown")
        assert resp.status_code == 404

    def test_test_cases_returns_total(self):
        _seed_session(self.run_id, stage="running", total=5)
        resp = client.get(f"/api/v1/test-runner/test-cases/{self.run_id}")
        assert resp.status_code == 200
        assert resp.json()["total_test_cases"] == 5

    def test_results_returns_summary_when_complete(self):
        _seed_session(self.run_id, stage="complete")
        resp = client.get(f"/api/v1/test-runner/results/{self.run_id}")
        assert resp.status_code == 200
        assert resp.json()["summary"]["total"] == 10


# ── Health check ──────────────────────────────────────────────────────────────


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_root():
    resp = client.get("/")
    assert resp.status_code == 200
