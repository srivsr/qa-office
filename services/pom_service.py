"""
POM service — DOM extraction, LLM semantic naming, PageMap construction.
Called exclusively by A14 POM Builder. No agents import this directly.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from schemas import AppConfig, PageElement, PageMap

logger = logging.getLogger(__name__)

_INTERACTIVE_TAGS = {"button", "input", "select", "textarea", "a", "label"}


def _page_name_from_url(url: str) -> str:
    """Convert URL path to PascalCase page class name, e.g. /auth/login → LoginPage."""
    path = urlparse(url).path.rstrip("/") or "/"
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "HomePage"
    name = "".join(p.title() for p in parts[-2:])  # last two segments
    name = re.sub(r"[^A-Za-z0-9]", "", name)
    return name + "Page" if name else "UnknownPage"


def extract_dom_elements(page, url: str) -> List[Dict[str, Any]]:
    """
    Navigate to url and extract all interactive elements via Playwright evaluate.
    Returns list of raw dicts: {tag, type, id, name, aria_label, text, placeholder}.
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(800)
    except Exception as exc:
        logger.warning("POM navigate failed for %s: %s", url, exc)
        return []

    try:
        elements = page.evaluate(
            """() => {
            const tags = ['button','input','select','textarea','a','[role="button"]',
                          '[role="link"]','[role="checkbox"]','[role="menuitem"]'];
            const seen = new Set();
            const results = [];
            tags.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    const key = (el.tagName + el.id + el.name + (el.getAttribute('aria-label')||'') +
                                 el.textContent.trim().slice(0,50)).toLowerCase();
                    if (seen.has(key) || !el.offsetParent) return;
                    seen.add(key);
                    results.push({
                        tag: el.tagName.toLowerCase(),
                        type: el.type || '',
                        id: el.id || '',
                        name: el.name || '',
                        aria_label: el.getAttribute('aria-label') || '',
                        placeholder: el.placeholder || '',
                        text: (el.innerText || el.textContent || '').trim().slice(0, 80),
                        href: el.href || '',
                        role: el.getAttribute('role') || ''
                    });
                });
            });
            return results.slice(0, 80);
        }"""
        )
        return elements or []
    except Exception as exc:
        logger.warning("POM DOM extraction failed for %s: %s", url, exc)
        return []


def build_llm_prompt(url: str, elements: List[Dict[str, Any]]) -> str:
    elems_text = json.dumps(elements, indent=2)
    return f"""You are a QA automation expert. Given raw DOM elements from page URL:
{url}

Elements:
{elems_text}

Generate a JSON array of page elements with semantic Python identifier names.
Each item must have:
  - python_name: SCREAMING_SNAKE_CASE identifier (e.g. EMAIL_INPUT, LOGIN_BUTTON)
  - tag: element tag from input
  - locator: Playwright locator expression (use get_by_role/get_by_label/get_by_placeholder/locator priority)
  - description: what this element does in plain English
  - stability: "stable" if aria-label/role/label exists, else "fragile"

Prefer locator strategies in this order:
1. page.get_by_role("button", name="...") for buttons/links with text
2. page.get_by_label("...") for inputs with labels
3. page.get_by_placeholder("...") for inputs with placeholder
4. page.locator("[aria-label='...']") for aria-label
5. page.locator("css-selector") as last resort

Only include elements useful for test automation (skip purely decorative elements).
Return ONLY a JSON array, no markdown fences, no commentary."""


def parse_llm_elements(raw: str, url: str) -> List[PageElement]:
    """Parse LLM JSON response into PageElement list."""
    raw = raw.strip()
    # Strip markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            data = data.get("elements", [])
        return [PageElement(**item) for item in data if isinstance(item, dict)]
    except Exception as exc:
        logger.error("POM parse_llm_elements failed for %s: %s", url, exc)
        return []


def build_page_map(url: str, elements: List[PageElement]) -> PageMap:
    class_name = _page_name_from_url(url)
    return PageMap(
        page_name=class_name,
        url=url,
        class_name=class_name,
        elements=elements,
    )


def discover_page_urls(base_url: str, app_config: AppConfig) -> List[str]:
    """
    Return pages to map. Uses explicit page_urls if provided;
    otherwise falls back to base_url only.
    """
    if app_config.page_urls:
        urls = []
        for u in app_config.page_urls:
            if not u.startswith("http"):
                urls.append(base_url.rstrip("/") + "/" + u.lstrip("/"))
            else:
                urls.append(u)
        return urls
    return [base_url]
