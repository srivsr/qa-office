"""
LLM client — thin adapter over Anthropic SDK.
Swap model with one config change; agents never touch the SDK directly.
Every call logs token cost and latency (CODING_STANDARDS §9, §13, §14).
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Thin wrapper around the Anthropic Messages API.

    Usage:
        llm = LLMClient(model="claude-sonnet-4-6", settings=settings)
        text = llm.complete(prompt, max_tokens=1024)

    Failure modes:
    - APITimeoutError   → raises (caller decides retry)
    - APIStatusError    → raises (caller decides retry — 429 is retryable)
    - ValidationError   → raises immediately (prompt issue, not retryable)
    """

    def __init__(self, model: str, settings) -> None:
        self.model = model
        self._timeout = settings.llm_timeout_s
        self._api_key = settings.anthropic_api_key
        self._client = self._build_client()

    def complete(
        self,
        prompt: str,
        max_tokens: int = 1024,
        run_id: Optional[str] = None,
        prompt_version: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> str:
        """
        Send prompt and return response text.

        Args:
            prompt:         Full prompt string (system + user merged for simplicity)
            max_tokens:     Hard cap — never unlimited
            run_id:         Trace ID for log correlation
            prompt_version: e.g. "a02_intent_v1" — logged with every call

        Returns:
            Raw response text (caller parses/validates)

        Raises:
            anthropic.APITimeoutError, anthropic.APIStatusError on transient failure
        """
        t0 = time.time()
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            timeout=timeout if timeout is not None else self._timeout,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = int((time.time() - t0) * 1000)
        usage = response.usage

        logger.info(
            "LLM complete",
            extra={
                "run_id": run_id,
                "prompt_version": prompt_version,
                "model": self.model,
                "latency_ms": latency_ms,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            },
        )
        return response.content[0].text

    def _build_client(self):
        import anthropic

        # Don't pass api_key=None explicitly — that blocks SDK env-var fallback.
        # Only pass it when we have a real value; otherwise let SDK read ANTHROPIC_API_KEY.
        kwargs = {"api_key": self._api_key} if self._api_key else {}
        return anthropic.Anthropic(**kwargs)
