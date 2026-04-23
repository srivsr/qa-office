"""
A14 POM Builder — proactively maps application pages into Python Page Object classes.
One job: AppConfig → AgentResult(artifacts={"pom_result": POMResult}).
LLM: claude-sonnet-4-6. Autonomy: L3. Confidence threshold: 0.80.
All business logic in services/pom_service.py. File writing in tools/pom_writer.py.
POM cache persisted via A9 Memory Keeper (pom_cache + pom_elements).
"""

import importlib.util
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from config.settings import settings as default_settings
from schemas import AgentResult, AppConfig, MemoryWrite, PageMap, POMResult
from services import pom_service
from tools.llm_client import LLMClient
from tools.pom_writer import write_all, write_init

logger = logging.getLogger(__name__)

_EXECUTOR_FILE = (
    Path(__file__).parents[1] / "qa-os" / "backend" / "app" / "services" / "parallel_executor.py"
)


def _make_browser_page(app_config: AppConfig) -> Any:
    """Create a synchronous Playwright page with optional auth state."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    context_kwargs: dict = {"headless": True}
    if app_config.auth_state:
        context_kwargs["storage_state"] = app_config.auth_state
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(**{k: v for k, v in context_kwargs.items() if k != "headless"})
    if app_config.auth_state:
        context = browser.new_context(storage_state=app_config.auth_state)
    else:
        context = browser.new_context()
    page = context.new_page()
    return pw, browser, context, page


class A14POMBuilder:
    """
    Navigates every page in AppConfig, extracts DOM elements,
    uses Claude to assign semantic names, generates Python PageObject files,
    and persists the POM cache in A9 Memory Keeper.

    Input:  AppConfig (base_url, page_urls, auth_state)
    Output: AgentResult
              artifacts={"pom_result": POMResult.model_dump()}
              metrics={"pages_mapped": int, "elements_found": int, "duration_ms": int}
    """

    CONFIDENCE_THRESHOLD = 0.80

    def __init__(self, settings=None, memory=None) -> None:
        self._settings = settings or default_settings
        self._llm = LLMClient(model=self._settings.a14_model, settings=self._settings)
        self._memory = memory  # injected A9MemoryKeeper; lazy-loaded if None

    def run(self, app_config: AppConfig, run_id: Optional[str] = None) -> AgentResult:
        run_id = run_id or uuid.uuid4().hex[:8]
        t0 = time.time()
        logger.info("A14 start", extra={"run_id": run_id, "base_url": app_config.base_url})

        urls = pom_service.discover_page_urls(app_config.base_url, app_config)
        page_maps = []

        # Check A9 cache first — skip pages that are fresh
        stale_urls = []
        for url in urls:
            cached = self._query_pom_cache(url)
            if cached:
                try:
                    elements_data = json.loads(cached["elements_json"])
                    from schemas import PageElement
                    elements = [PageElement(**e) for e in elements_data]
                    page_maps.append(PageMap(
                        page_name=cached["page_name"],
                        url=url,
                        class_name=cached["class_name"],
                        elements=elements,
                    ))
                    logger.info("A14 cache hit: %s", url)
                    continue
                except Exception as exc:
                    logger.warning("A14 cache parse error for %s: %s", url, exc)
            stale_urls.append(url)

        if stale_urls:
            live_maps = self._map_pages_live(stale_urls, app_config, run_id)
            for pm in live_maps:
                self._persist_pom(pm, run_id)
            page_maps.extend(live_maps)

        if not page_maps:
            ms = int((time.time() - t0) * 1000)
            return AgentResult(
                status="error",
                confidence=0.0,
                error_message="No pages could be mapped",
                metrics={"duration_ms": ms},
            )

        # Write page object files
        try:
            files = write_all(page_maps)
            files.append(write_init(page_maps))
        except Exception as exc:
            logger.error("A14 pom_writer error: %s", exc)
            files = []

        total_elements = sum(len(pm.elements) for pm in page_maps)
        ms = int((time.time() - t0) * 1000)
        # 1 page → 0.80 (at threshold); grows by 0.04 per additional page, capped at 0.98
        confidence = min(0.98, 0.80 + 0.04 * (len(page_maps) - 1)) if page_maps else 0.0

        pom_result = POMResult(
            run_id=run_id,
            pages_mapped=len(page_maps),
            elements_found=total_elements,
            files_generated=files,
            page_maps=page_maps,
        )

        logger.info(
            "A14 complete",
            extra={
                "run_id": run_id,
                "pages": len(page_maps),
                "elements": total_elements,
                "duration_ms": ms,
            },
        )

        status = "success" if confidence >= self.CONFIDENCE_THRESHOLD else "review"
        return AgentResult(
            status=status,
            confidence=confidence,
            review_required=(status == "review"),
            artifacts={"pom_result": pom_result.model_dump()},
            metrics={"pages_mapped": len(page_maps), "elements_found": total_elements, "duration_ms": ms},
        )

    # ── live mapping ──────────────────────────────────────────────────────────

    def _map_pages_live(self, urls: list, app_config: AppConfig, run_id: str) -> list:
        page_maps = []
        pw = browser = context = page = None
        try:
            pw, browser, context, page = _make_browser_page(app_config)
            for url in urls:
                pm = self._map_one_page(page, url, run_id)
                if pm:
                    page_maps.append(pm)
        except Exception as exc:
            logger.error("A14 Playwright error: %s", exc)
        finally:
            for obj in (page, context, browser, pw):
                if obj:
                    try:
                        obj.close()
                    except Exception:
                        pass
        return page_maps

    def _map_one_page(self, page, url: str, run_id: str) -> Optional[PageMap]:
        raw_elements = pom_service.extract_dom_elements(page, url)
        if not raw_elements:
            logger.warning("A14 no elements found at %s", url)
            return None

        prompt = pom_service.build_llm_prompt(url, raw_elements)
        try:
            raw_response = self._llm.complete(
                prompt,
                max_tokens=self._settings.a14_max_tokens,
                run_id=run_id,
                prompt_version="a14_pom_v1",
            )
        except Exception as exc:
            logger.error("A14 LLM error for %s: %s", url, exc)
            return None

        elements = pom_service.parse_llm_elements(raw_response, url)
        if not elements:
            return None

        return pom_service.build_page_map(url, elements)

    # ── A9 persistence ─────────────────────────────────────────────────────────

    def _get_memory(self):
        if self._memory is None:
            from agents.a09_memory_keeper import A9MemoryKeeper
            self._memory = A9MemoryKeeper()
        return self._memory

    def _persist_pom(self, pm: PageMap, run_id: str) -> None:
        elements_json = json.dumps([e.model_dump() for e in pm.elements])
        self._get_memory().write(
            MemoryWrite(
                source_agent="A14",
                record_type="pom_cache",
                run_id=run_id,
                test_case_id="__pom__",
                module=pm.page_name,
                payload={
                    "page_url": pm.url,
                    "page_name": pm.page_name,
                    "class_name": pm.class_name,
                    "elements_json": elements_json,
                    "ttl_days": 7,
                },
            )
        )
        # Index each element in ChromaDB for semantic search by A3
        for el in pm.elements:
            self._get_memory().write(
                MemoryWrite(
                    source_agent="A14",
                    record_type="pom_element",
                    run_id=run_id,
                    test_case_id="__pom__",
                    module=pm.page_name,
                    payload={
                        "doc_id": f"{pm.page_name}_{el.python_name}",
                        "text": f"{el.description} {el.python_name} {el.locator}",
                        "metadata": {
                            "page": pm.page_name,
                            "url": pm.url,
                            "locator": el.locator,
                            "python_name": el.python_name,
                            "stability": el.stability,
                        },
                    },
                )
            )

    def _query_pom_cache(self, url: str) -> Optional[dict]:
        try:
            from memory import db
            return db.get_pom_cache(url)
        except Exception as exc:
            logger.debug("A14 pom cache miss for %s: %s", url, exc)
            return None
