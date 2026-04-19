"""
QA Office configuration — loaded from environment / .env file.
Never hardcode credentials; always use env vars (SOC2 requirement).
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path so .env loads correctly regardless of uvicorn's CWD
_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Target app under test (NEVER point at production)
    app_test_url: str = ""
    app_username: str = ""
    app_password: str = ""

    # Playwright
    headless: bool = True
    timeout_ms: int = 30000
    screenshot_each_step: bool = True

    # Execution mode for qa-os runner
    # page_check — regex Playwright (no AI, default)
    # scriptless — AI decides action per step live (needs openai_api_key)
    # scripted   — AI generates full .py script, saves to disk (needs openai_api_key)
    execution_mode: str = "page_check"
    openai_api_key: str = ""

    # Retry (FR2: up to 3 retries with exponential backoff)
    max_retries: int = 3
    retry_backoff_base_ms: int = 1000  # 1s → 2s → 4s

    # Confidence thresholds — ACT / REVIEW / PAUSE
    act_threshold: float = 0.85
    review_threshold: float = 0.60

    # LLM credentials (CODING_STANDARDS §8)
    anthropic_api_key: str = ""
    llm_timeout_s: int = 120  # default; A0 overrides to a0_llm_timeout_s

    # Clerk auth (passed to Playwright runner)
    clerk_secret_key: str = ""
    app_auth_enabled: bool = False
    app_auth_type: str = "clerk"

    # Per-agent model routing — override in .env for production (sonnet/opus)
    a2_model: str = "claude-sonnet-4-6"
    a3_model: str = "claude-sonnet-4-6"
    a5_model: str = "claude-sonnet-4-6"  # sonnet instead of opus for cost
    a6_model: str = "claude-sonnet-4-6"
    a10_model: str = "claude-sonnet-4-6"
    a11_model: str = "claude-sonnet-4-6"  # sonnet instead of opus for cost

    # Per-agent LLM timeout — A0 needs more time for full SRS generation
    a0_llm_timeout_s: int = 180

    # Per-agent max_tokens — never unlimited (CLAUDE_ADDITIONS.md)
    a0_max_tokens: int = 4096  # needs room for 8 full test cases from an SRS
    a2_max_tokens: int = 2048
    a3_max_tokens: int = 2048
    a5_max_tokens: int = 2048
    a6_max_tokens: int = 512
    a11_max_tokens: int = 2048
    max_context_tokens: int = 16000

    # A7 HITL timeout
    a7_timeout_s: int = 300  # 5 minutes

    # A11 Opus model for high-risk decisions
    a11_opus_model: str = "claude-opus-4-6"

    # A12 Data Seeder
    a12_model: str = "claude-sonnet-4-6"
    a12_max_tokens: int = 1024

    # A13 Environment Guardian
    a13_model: str = "claude-sonnet-4-6"
    a13_max_tokens: int = 1024

    # A10 Planner
    a10_model: str = "claude-sonnet-4-6"
    a10_max_tokens: int = 2048
    a10_reflection_max_tokens: int = 1024
    a10_reflection_ttl_days: int = 90

    # A14 POM Builder
    a14_model: str = "claude-sonnet-4-6"
    a14_max_tokens: int = 4096
    a14_pom_ttl_days: int = 7
    a14_rebuild_threshold: float = 0.20  # rebuild POM if A6 repair rate > 20%

    # A15 Script Reviewer
    a15_model: str = "claude-sonnet-4-6"
    a15_max_tokens: int = 1024
    a15_assertion_penalty: float = 0.15  # confidence penalty per unverified assertion


settings = Settings()
