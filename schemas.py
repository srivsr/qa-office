"""
Shared typed schemas for QA Office agent pipeline.
All agents communicate using these types — no raw dicts across boundaries.

Frozen contracts (DO NOT rename/remove fields after Phase 1):
  TestCase, ExecutionResult, StepResult, RunReport
New Phase 2 types (Pydantic — LLM structured outputs):
  ExecutableIntent, IntentStep, SelectorResult, FailureDiagnosis, HealResult
Standard envelope (every agent returns):
  AgentResult, AgentDecision
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


@dataclass
class TestCase:
    """Parsed test case from BlueTree Excel (output of A1 Ingestion)."""

    id: str
    module: str
    description: str
    steps: List[str]
    expected_result: str
    priority: str  # High / Medium / Low
    persona: Optional[str] = None
    pre_conditions: List[str] = field(default_factory=list)
    requires_live_verification: bool = False  # True when assertion uses dynamic/invented UI copy


@dataclass
class StepResult:
    """Execution outcome for a single test step (populated by A4 Executor)."""

    step_number: int
    action: str
    status: str  # passed / failed / error / unknown
    duration_ms: int
    screenshot_path: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class ExecutionResult:
    """Full execution result for one TestCase (output of A4 Executor)."""

    test_case_id: str
    status: str  # passed / failed / error
    duration_ms: int
    retry_count: int
    timestamp: str  # ISO-8601 UTC
    step_results: List[StepResult] = field(default_factory=list)
    error_message: Optional[str] = None
    screenshot_paths: List[str] = field(default_factory=list)


@dataclass
class RunReport:
    """Summary of a completed run (output of A8 Report Builder)."""

    run_id: str
    html_path: str
    excel_path: str
    total: int
    passed: int
    failed: int
    error: int
    pass_rate: float
    skipped: int = 0
    duration_ms: int = 0
    results: List[Any] = field(default_factory=list)


# ── Standard envelope — every agent returns AgentResult ──────────────────────


class AgentDecision(str, Enum):
    ACT = "act"  # confidence >= 0.85 — proceed autonomously
    REVIEW = "review"  # confidence 0.60–0.85 — proceed but flag for human
    PAUSE = "pause"  # confidence < 0.60 — stop, escalate to A7


class AgentResult(BaseModel):
    """Standard result envelope returned by every agent."""

    status: str  # "success" | "review" | "pause" | "error"
    confidence: float  # 0.0 to 1.0
    error_code: Optional[str] = None  # SFC code e.g. "TOOL_UNAVAILABLE"
    error_message: Optional[str] = None
    retryable: bool = False
    review_required: bool = False
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)


# ── Phase 2 LLM output schemas (Pydantic — validated at LLM boundary) ────────


class IntentStep(BaseModel):
    step_number: int
    raw_action: str
    playwright_action: str  # click | fill | navigate | assert | select | wait
    selector: Optional[str] = None  # null for navigate steps
    value: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ExecutableIntent(BaseModel):
    test_case_id: str
    steps: List[IntentStep]
    confidence: float = Field(ge=0.0, le=1.0)
    persona: str
    ambiguities: List[str] = Field(default_factory=list)


class SelectorStep(BaseModel):
    step_number: int
    selector: str
    strategy: str  # aria-label | data-testid | role | label | text | css | xpath
    stability_score: float = Field(ge=0.0, le=1.0)
    fallback_list: List[str] = Field(default_factory=list)


class SelectorResult(BaseModel):
    test_case_id: str
    selectors: List[SelectorStep]
    overall_confidence: float = Field(ge=0.0, le=1.0)


class FailureDiagnosis(BaseModel):
    test_case_id: str
    sfc_code: str  # e.g. "TOOL_SELECTION_WRONG"
    sfc_number: int  # 0–12
    root_cause: str
    fix_direction: str
    confidence: float = Field(ge=0.0, le=1.0)


class HealResult(BaseModel):
    test_case_id: str
    original_selector: str
    fixed_selector: str
    strategy: str
    confidence: float = Field(ge=0.0, le=1.0)
    log: str


# ── Dataclass for stable selector candidates (internal immutable object) ──────


@dataclass(frozen=True)
class SelectorCandidate:
    value: str
    strategy: str
    stability_score: float


# ── Phase 3 — A9 Memory Keeper schemas ───────────────────────────────────────


class MemoryWrite(BaseModel):
    """Input to A9 write() — one memory record to persist."""

    source_agent: str  # e.g. "A4", "A5", "A6"
    record_type: str  # "run" | "selector" | "human_decision" | "insight" | "narrative" | "domain"
    run_id: str
    test_case_id: str
    module: str = "General"
    payload: Dict[str, Any] = Field(default_factory=dict)


class MemoryQuery(BaseModel):
    """Input to A9 query() — lookup request."""

    query_type: (
        str  # "run_history" | "selector" | "similar_failures" | "domain" | "insights"
    )
    test_case_id: Optional[str] = None
    selector_value: Optional[str] = None
    agent_id: Optional[str] = None
    text: Optional[str] = None  # semantic search text
    limit: int = 10


class MemoryResult(BaseModel):
    """Output from A9 write() or query()."""

    success: bool
    records: List[Dict[str, Any]] = Field(default_factory=list)
    error_message: Optional[str] = None


# ── Phase 4 — A7 Reviewer + A11 QA Director schemas ──────────────────────────


class SubGoal(BaseModel):
    """One test-case-level sub-goal tracked by A11."""

    id: str
    test_case_id: str
    priority: str = "medium"
    agents: List[str] = Field(default_factory=list)
    status: str = "pending"  # pending | running | complete | paused | error


class ReviewRequest(BaseModel):
    """Input to A7 Reviewer — escalation from any agent."""

    run_id: str
    test_case_id: str
    agent_result: Dict[str, Any]
    reason: str
    source_agent: str  # "A2" | "A3" | "A5" | "A6"


class ReviewDecision(BaseModel):
    """Output from A7 Reviewer — human decision."""

    run_id: str
    test_case_id: str
    approved: bool
    send_back_to: Optional[str] = None  # "A2" | "A5" | "A6" | "A12" | None
    comment: Optional[str] = None
    decided_by: str = "human"
    timestamp: Optional[str] = None


class QAMission(BaseModel):
    """Input to A11 QA Director — top-level test run mission."""

    excel_path: str
    app_url: str
    app_name: str = ""
    persona: str = "QA Engineer"
    output_dir: str = "runs"
    seed_required: bool = False
    seed_config: Optional["SeedConfig"] = None
    run_request: Optional["RunRequest"] = None  # if set, A10 planning runs
    execution_mode: str = "page_check"  # page_check | scriptless | scripted
    openai_api_key: str = ""            # required for scriptless / scripted
    pom_config: Optional[Dict[str, Any]] = None  # {page_urls, auth_state} for A14


class MissionResult(BaseModel):
    """Output from A11 QA Director — aggregated mission summary."""

    run_id: str
    total: int
    passed: int = 0
    failed: int = 0
    error: int = 0
    pass_rate: float = 0.0
    html_path: Optional[str] = None
    excel_path_report: Optional[str] = None
    paused_count: int = 0
    patterns: List[str] = Field(default_factory=list)
    proactive_alerts: List["ProactiveAlert"] = Field(default_factory=list)


# ── Phase 6 — A10 Planner + A11 Emergent Synthesis schemas ──────────────────


class RunRequest(BaseModel):
    """Input to A10 Planner — controls scope and mission type."""

    modules: List[str] = Field(default_factory=list)  # empty = use all from A1
    persona: str = "default"
    mission_type: str = "regression"  # "regression" | "smoke" | "compliance"
    constraints: Dict[str, Any] = Field(default_factory=dict)


class RiskScore(BaseModel):
    """Per-module risk score computed by A10 from A9 history."""

    module: str
    score: float = Field(ge=0.0, le=1.0, default=0.5)
    failure_frequency: float = 0.0
    compliance_criticality: float = 0.0
    self_heal_count: int = 0
    time_since_last_pass_days: float = 0.0
    rationale: str = ""


class TestPlan(BaseModel):
    """Output from A10 Planner — ordered test cases with risk rationale."""

    run_id: str
    ordered_test_case_ids: List[str]
    risk_scores: List[RiskScore] = Field(default_factory=list)
    rationale: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.9)


class ReflectionInsight(BaseModel):
    """A10 post-run reflection — prediction vs actual, weight adjustments."""

    run_id: str
    predicted_high_risk: List[str]  # test_case_ids A10 placed in top half
    actual_failures: List[str]
    prediction_accuracy: float = Field(ge=0.0, le=1.0, default=0.0)
    miscalibrated_modules: List[str] = Field(default_factory=list)
    weight_adjustments: Dict[str, float] = Field(default_factory=dict)
    rationale: str = ""


class ProactiveAlert(BaseModel):
    """Emergent signal detected by A11 Opus synthesis."""

    alert_type: str  # "instability" | "systemic_bug" | "model_drift"
    module: str
    signal: str  # human-readable description
    severity: str = "medium"  # "low" | "medium" | "high"
    recommendation: str = ""


# ── Phase 5 — A12 Data Seeder schemas ────────────────────────────────────────


class SeedConfig(BaseModel):
    """Configuration for A12 Data Seeder."""

    modules: List[str] = Field(default_factory=list)
    clean_before_seed: bool = True
    max_records: int = 10


class SeedRecipe(BaseModel):
    """One seeding action generated by A12."""

    module: str
    action: str  # "create_employee" | "add_punch_data" | "setup_compliance"
    payload: Dict[str, Any] = Field(default_factory=dict)
    is_compliance_data: bool = False


class SeedResult(BaseModel):
    """Output from A12 Data Seeder."""

    run_id: str
    seeded: bool
    modules: List[str] = Field(default_factory=list)
    recipes_applied: int = 0
    warnings: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None


# ── Phase 5 — A13 Environment Guardian schemas ────────────────────────────────


class EnvConfig(BaseModel):
    """Input to A13 Environment Guardian."""

    app_url: str
    auth_url: Optional[str] = None
    latency_threshold_ms: int = 3000
    check_feature_flags: bool = False


class HealthCheck(BaseModel):
    """Result of one pre-run health check."""

    name: str  # "url_reachable" | "auth_responding" | "latency_ok"
    passed: bool
    detail: Optional[str] = None


class HealthStatus(BaseModel):
    """Output from A13 Environment Guardian."""

    run_id: str
    status: str  # "healthy" | "degraded" | "unavailable"
    checks: List[HealthCheck] = Field(default_factory=list)
    overall_score: float = 0.0
    error_message: Optional[str] = None


# ── Phase 5 — A8 compliance metadata ─────────────────────────────────────────


class ComplianceMetadata(BaseModel):
    """SOC2 audit trail attached to every run report."""

    run_id: str
    run_hash: str  # SHA256(run_id + timestamp + sorted tc IDs)
    signed_timestamp: str  # ISO-8601 UTC
    env_health: Optional[str] = None  # "healthy" | "degraded" | "unavailable"
    seed_summary: Optional[str] = None  # e.g. "3 recipes, 2 modules"
    chain_of_custody: List[str] = Field(default_factory=list)  # ordered agent list


# ── A14 POM Builder schemas ───────────────────────────────────────────────────


class AppConfig(BaseModel):
    """Input to A14 POM Builder."""

    base_url: str
    page_urls: List[str] = Field(default_factory=list)
    auth_state: Optional[Dict[str, Any]] = None  # Playwright storage_state dict


class PageElement(BaseModel):
    """One discovered interactive element on a page."""

    tag: str  # "button" | "input" | "select" | "textarea" | "a" | "checkbox"
    python_name: str  # semantic identifier, e.g. "EMAIL_INPUT"
    locator: str  # Playwright expression e.g. 'page.get_by_label("Email")'
    description: str  # human-readable purpose
    stability: str = "stable"  # "stable" | "fragile"


class PageMap(BaseModel):
    """All elements discovered on one page."""

    page_name: str  # e.g. "LoginPage"
    url: str
    class_name: str  # e.g. "LoginPage"
    elements: List[PageElement] = Field(default_factory=list)


class POMResult(BaseModel):
    """Output from A14 POM Builder."""

    run_id: str
    pages_mapped: int = 0
    elements_found: int = 0
    files_generated: List[str] = Field(default_factory=list)
    page_maps: List[PageMap] = Field(default_factory=list)
    error_message: Optional[str] = None


# ── A15 Script Reviewer schemas ───────────────────────────────────────────────


class AssertionFlag(BaseModel):
    """One flagged assertion step detected by A15 validate_assertions."""

    step_number: int
    flag_type: str       # PRICE | STEP_COUNTER | EMOJI | LOADING_STATE | DYNAMIC_COUNT
    original_text: str
    suggestion: str      # semantic replacement e.g. "verify price element is visible"
    confidence_penalty: float = 0.15


class AssertionReport(BaseModel):
    """Summary of all flagged assertions in one ExecutableIntent."""

    test_case_id: str
    flags: List[AssertionFlag] = Field(default_factory=list)
    total_penalty: float = 0.0
    has_unverified: bool = False


class ScriptReview(BaseModel):
    """Output of A15 review_script skill."""

    test_case_id: str
    assertion_report: AssertionReport
    confidence_adjustment: float = 0.0   # negative when assertions are flagged
    warnings: List[str] = Field(default_factory=list)
    approved: bool = True
