#!/usr/bin/env python
"""Keep the Streamlit demo awake on Streamlit Community Cloud.

Streamlit Community Cloud suspends apps that receive no viewer traffic.
A simple HTTP GET (like curl) does not establish a WebSocket connection and
cannot click the "Yes, get this app back up!" button if the app is already
sleeping.

This script launches a headless browser via Playwright:
1. Navigates to the deployed Streamlit app URL.
2. Detects if the app has gone to sleep due to inactivity.
3. If asleep, clicks the wake-up button and waits for the app container to boot.
4. If awake, maintains an active WebSocket session for several seconds so
   Streamlit Cloud resets its inactivity timer.
5. Writes status to GitHub Step Summary when running under GitHub Actions.

Usage:
    python scripts/keep_awake.py [--url URL] [--headless]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

DEFAULT_APP_URL = "https://spectrax-anveshak-sih26055-prototype.streamlit.app/"


def _log_summary(msg: str) -> None:
    """Append a message to GitHub Step Summary if running in GitHub Actions."""
    summary_path_raw = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path_raw:
        summary_path = Path(summary_path_raw)
        if summary_path.exists():
            with summary_path.open("a", encoding="utf-8") as f:
                f.write(msg + "\n")


def wake_streamlit_app(url: str, headless: bool = True, wait_seconds: int = 12) -> bool:
    """Open the Streamlit app in Playwright, wake if sleeping, and keep alive."""
    from playwright.sync_api import sync_playwright

    print(f"Target URL: {url}")
    print(f"Launching headless browser (headless={headless})...", flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            print("Navigating to app URL...", flush=True)
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)

            # Give single-page app wrapper time to resolve auth and render status
            time.sleep(5)

            # Search main page and all frames for wake-up button or sleep text
            wake_button = None
            is_sleeping = False

            frames_to_check = [page, *page.frames]
            for frame in frames_to_check:
                # Common Streamlit sleep button texts
                for pattern in [
                    "text='Yes, get this app back up!'",
                    "text='Yes, get this app back up'",
                    "text='Get this app back up'",
                    "button:has-text('Yes, get this app back up!')",
                    "button:has-text('wake up')",
                ]:
                    locator = frame.locator(pattern)
                    if locator.count() > 0:
                        wake_button = locator.first
                        is_sleeping = True
                        break
                if is_sleeping:
                    break

                try:
                    frame_text = frame.inner_text("body")
                    if "gone to sleep" in frame_text.lower() or "sleeping" in frame_text.lower():
                        is_sleeping = True
                        btn_candidates = frame.locator("button").all()
                        for btn in btn_candidates:
                            txt = (btn.inner_text() or "").lower()
                            if "back up" in txt or "wake" in txt or "yes" in txt:
                                wake_button = btn
                                break
                except Exception:
                    continue

                if is_sleeping:
                    break

            if is_sleeping and wake_button:
                print("App is asleep! Clicking 'Yes, get this app back up!' button...", flush=True)
                wake_button.click()
                print("Clicked. Waiting up to 60s for Streamlit container to boot...", flush=True)

                # Wait for container boot and real content to appear
                deadline = time.time() + 60
                woken = False
                while time.time() < deadline:
                    time.sleep(4)
                    for frame in [page, *page.frames]:
                        try:
                            body = frame.inner_text("body")
                            if "ANVESHAK" in body or frame.locator(".stApp").count() > 0:
                                woken = True
                                break
                        except Exception:
                            continue
                    if woken:
                        break

                if woken:
                    msg = "### Streamlit App Awakened\nApp was sleeping. Successfully clicked wake-up button and booted container."
                    print(msg, flush=True)
                    _log_summary(msg)
                    return True
                else:
                    msg = "### Wake-up Click Sent\nClicked wake-up button; app container is in boot process."
                    print(msg, flush=True)
                    _log_summary(msg)
                    return True

            print("No sleep modal detected. Checking active app connection...", flush=True)
            # Confirm the app is rendering
            app_rendered = False
            for frame in [page, *page.frames]:
                try:
                    body = frame.inner_text("body")
                    if "ANVESHAK" in body or frame.locator(".stApp").count() > 0:
                        app_rendered = True
                        break
                except Exception:
                    continue

            # Hold connection open so WebSocket viewer session registers with Streamlit Cloud
            print(f"Holding connection open for {wait_seconds}s to register viewer traffic...", flush=True)
            time.sleep(wait_seconds)

            status_note = "App active and content verified (ANVESHAK)." if app_rendered else "App page loaded and session registered."
            msg = f"### Streamlit Demo Awake\n{status_note} Held active WebSocket session for {wait_seconds}s."
            print(msg, flush=True)
            _log_summary(msg)
            return True

        except Exception as exc:
            err = f"Failed to keep app awake: {exc}"
            print(f"::error::{err}", file=sys.stderr)
            _log_summary(f"### Keep-Awake Failed\n{err}")
            return False
        finally:
            browser.close()


def main() -> int:
    """Parse CLI args and execute keep-awake."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.getenv("STREAMLIT_APP_URL", DEFAULT_APP_URL).strip(),
        help="URL of the deployed Streamlit app.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in headed mode (for local debugging).",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=12,
        help="Seconds to hold WebSocket connection open.",
    )
    args = parser.parse_args()

    url = args.url or DEFAULT_APP_URL
    success = wake_streamlit_app(url=url, headless=not args.headed, wait_seconds=args.wait)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
