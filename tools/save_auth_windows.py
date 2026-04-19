"""
Run this from Windows PowerShell (NOT WSL2):
    python C:/Srithar/srivsr_os/apps/qa-office/tools/save_auth_windows.py

Opens a real Chrome window. Log in to EvalKit (complete any OTP).
Saves auth_state.json that the QA pipeline will use automatically.
"""

import json
from pathlib import Path

APP_URL = "https://evalkit.srivsr.com"
# Save next to this script so WSL2 can read it at /mnt/c/...
OUT_PATH = Path(__file__).parent.parent / "auth_state.json"


def main():
    from playwright.sync_api import sync_playwright

    print(f"Opening browser → {APP_URL}/sign-in")
    print(
        "Log in (complete OTP if prompted), land on dashboard, then press Enter here.\n"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{APP_URL}/sign-in", wait_until="domcontentloaded")

        input(">>> Press Enter once you are on the dashboard... ")

        state = context.storage_state()
        OUT_PATH.write_text(json.dumps(state, indent=2))
        print(f"\n✅  Saved: {OUT_PATH}")
        print("The QA pipeline will now use this session automatically.")
        browser.close()


if __name__ == "__main__":
    main()
