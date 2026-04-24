"""
Run this from Windows PowerShell (NOT WSL2):
    python C:/path/to/qa-office-prod/tools/save_auth_windows.py

Opens a real Chrome window. Log in to your app (complete any OTP).
Saves auth_state.json that the QA pipeline will use automatically.

Requires APP_TEST_URL set in your .env file.
"""

import json
import os
import sys
from pathlib import Path

_QA_ROOT = Path(__file__).parent.parent
OUT_PATH = _QA_ROOT / "auth_state.json"


def _get_app_url() -> str:
    env_file = _QA_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("APP_TEST_URL="):
                return line.partition("=")[2].strip().strip('"').strip("'").rstrip("/")
    url = os.environ.get("APP_TEST_URL", "")
    if not url:
        sys.exit("APP_TEST_URL is not set. Add it to your .env file.")
    return url.rstrip("/")


def main():
    from playwright.sync_api import sync_playwright

    app_url = _get_app_url()
    print(f"Opening browser → {app_url}/sign-in")
    print(
        "Log in (complete OTP if prompted), land on dashboard, then press Enter here.\n"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{app_url}/sign-in", wait_until="domcontentloaded")

        input(">>> Press Enter once you are on the dashboard... ")

        state = context.storage_state()
        OUT_PATH.write_text(json.dumps(state, indent=2))
        print(f"\n✅  Saved: {OUT_PATH}")
        print("The QA pipeline will now use this session automatically.")
        browser.close()


if __name__ == "__main__":
    main()
