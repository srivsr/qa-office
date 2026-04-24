"""
Save Clerk auth state to auth_state.json for use by the QA pipeline.

Two modes:

  Headed (local machine — opens a real browser window):
      python3 tools/save_auth_state.py

  Headless (SSH / bash / CI — fills the login form automatically):
      python3 tools/save_auth_state.py --headless --email you@example.com --password yourpass

The saved auth_state.json is picked up automatically by all future runs.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from config.settings import settings

AUTH_STATE_PATH = Path(__file__).parents[1] / "auth_state.json"


# ── Headed mode (local, interactive) ─────────────────────────────────────────

def run_headed():
    from playwright.sync_api import sync_playwright

    app_url = settings.app_test_url or "https://evalkit.srivsr.com"
    print(f"Opening browser → {app_url}/sign-in")
    print("Log in manually (complete OTP/2FA if prompted), then press Enter here.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{app_url}/sign-in", wait_until="domcontentloaded")

        input(">>> Browser is open. Log in, then press Enter to save... ")

        if "/sign-in" in page.url:
            print("Still on sign-in — did login complete?")
            input("Press Enter again once you are on the dashboard... ")

        _save(context.storage_state())
        browser.close()


# ── Headless mode (SSH / CI) ──────────────────────────────────────────────────

async def run_headless(email: str, password: str):
    from playwright.async_api import async_playwright

    app_url = settings.app_test_url or "https://evalkit.srivsr.com"
    print(f"[headless] Logging in to {app_url}/sign-in as {email}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(f"{app_url}/sign-in", wait_until="domcontentloaded")
        await page.wait_for_load_state("load")

        # Fill email
        try:
            await page.fill('input[type="email"], input[name="identifier"]', email, timeout=10000)
            await page.click('button[type="submit"]', timeout=5000)
            print("[headless] Email submitted")
        except Exception as e:
            await browser.close()
            sys.exit(f"Could not fill email field: {e}")

        # Fill password if shown (Clerk shows it after email step)
        try:
            await page.wait_for_selector('input[type="password"]', timeout=8000)
            await page.fill('input[type="password"]', password)
            await page.click('button[type="submit"]', timeout=5000)
            print("[headless] Password submitted")
        except Exception:
            # Clerk may use magic link instead of password — fall back to OTP prompt
            print("[headless] No password field found — Clerk may have sent a magic link or OTP.")
            print("           Cannot complete headless login without a password-based account.")
            print("           Use headed mode instead: python3 tools/save_auth_state.py")
            await browser.close()
            sys.exit(1)

        # Wait for redirect away from sign-in
        try:
            await page.wait_for_url(lambda url: "/sign-in" not in url, timeout=15000)
            print(f"[headless] Logged in — landed on {page.url}")
        except Exception:
            await browser.close()
            sys.exit("Login did not complete — check credentials or use headed mode.")

        _save(await context.storage_state())
        await browser.close()


# ── Shared ────────────────────────────────────────────────────────────────────

def _save(state: dict):
    AUTH_STATE_PATH.write_text(json.dumps(state, indent=2))
    print(f"\n✅  Auth state saved → {AUTH_STATE_PATH}")
    print("    All future pipeline runs will use this session automatically.")


def main():
    parser = argparse.ArgumentParser(description="Save Clerk auth state for QA pipeline")
    parser.add_argument("--headless", action="store_true",
                        help="Run headless (no browser window) — for SSH/CI use")
    parser.add_argument("--email", default=settings.app_username,
                        help="Login email (defaults to APP_USERNAME in .env)")
    parser.add_argument("--password", default=settings.app_password,
                        help="Login password (defaults to APP_PASSWORD in .env)")
    args = parser.parse_args()

    if args.headless:
        if not args.email or not args.password:
            sys.exit("--headless requires --email and --password (or APP_USERNAME/APP_PASSWORD in .env)")
        asyncio.run(run_headless(args.email, args.password))
    else:
        run_headed()


if __name__ == "__main__":
    main()
