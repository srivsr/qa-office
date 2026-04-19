"""
One-time script: opens a headed browser to log in to EvalKit via Clerk,
then saves the browser storage state to auth_state.json.
All future pipeline runs reuse this state — no re-login needed.

Usage:
    python3 tools/save_auth_state.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from config.settings import settings

AUTH_STATE_PATH = Path(__file__).parents[1] / "auth_state.json"


def main():
    from playwright.sync_api import sync_playwright

    app_url = settings.app_test_url or "https://evalkit.srivsr.com"
    print(f"Opening headed browser → {app_url}")
    print("Log in manually (complete OTP if prompted), then press Enter here.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{app_url}/sign-in", wait_until="domcontentloaded")

        input("\n>>> Browser opened. Log in, then press Enter to save state... ")

        # Confirm we left sign-in
        current = page.url
        if "/sign-in" in current:
            print("Still on sign-in page — did login complete?")
            input("Press Enter again once you're on the dashboard... ")

        state = context.storage_state()
        AUTH_STATE_PATH.write_text(json.dumps(state, indent=2))
        print(f"\n✅ Auth state saved to {AUTH_STATE_PATH}")
        print("Pipeline will use this state automatically for all future runs.")
        browser.close()


if __name__ == "__main__":
    main()
