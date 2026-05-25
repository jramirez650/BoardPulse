import os
import json
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

log = logging.getLogger("boardpulse")

TEAM_NAME    = os.getenv("TEAMS_TEAM_NAME", "")
CHANNEL_NAME = os.getenv("TEAMS_CHANNEL_NAME", "")
SESSION_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".teams_session")


def send_to_teams(message: str) -> bool:
    with sync_playwright() as p:
        log.info(f"      Launching browser (session saved at: {SESSION_DIR})")

        context = p.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR,
            headless=False,
            slow_mo=300,
            args=["--start-maximized"],
            no_viewport=True,
        )

        page = context.pages[0] if context.pages else context.new_page()

        try:
            # ── 1. Navigate to Teams ──────────────────────────────────────
            log.info("      Navigating to Microsoft Teams...")
            page.goto("https://teams.microsoft.com", wait_until="domcontentloaded", timeout=30000)

            # First run: wait for the user to log in manually
            log.info("      Waiting for Teams to load (log in if prompted)...")
            page.wait_for_selector('[data-tid="app-bar"], [class*="teams-app"]',
                                   timeout=120000)
            page.wait_for_timeout(3000)

            # ── 2. Click the team ─────────────────────────────────────────
            log.info(f"      Clicking team: '{TEAM_NAME}'")
            page.get_by_text(TEAM_NAME, exact=True).first.click()
            page.wait_for_timeout(1500)

            # ── 3. Click the channel ──────────────────────────────────────
            log.info(f"      Clicking channel: '{CHANNEL_NAME}'")
            page.get_by_text(CHANNEL_NAME, exact=True).first.click()
            page.wait_for_timeout(1500)

            # ── 4. Find compose box ───────────────────────────────────────
            log.info("      Looking for message compose box...")
            selectors = [
                '[data-tid="ckeditor"]',
                '[aria-label="Type a message"]',
                'div[contenteditable="true"][role="textbox"]',
                'div[contenteditable="true"]',
            ]

            compose_box = None
            for sel in selectors:
                try:
                    el = page.locator(sel).last
                    if el.is_visible(timeout=2000):
                        compose_box = el
                        log.info(f"      Compose box found ({sel})")
                        break
                except Exception:
                    continue

            if not compose_box:
                raise Exception("Compose box not found — Teams UI may have changed")

            # ── 5. Paste message via clipboard ────────────────────────────
            log.info("      Pasting message...")
            context.grant_permissions(["clipboard-read", "clipboard-write"])
            page.evaluate(f"navigator.clipboard.writeText({json.dumps(message)})")
            compose_box.click()
            page.wait_for_timeout(500)
            page.keyboard.press("Control+a")
            page.keyboard.press("Control+v")
            page.wait_for_timeout(1000)

            # ── 6. Send ───────────────────────────────────────────────────
            log.info("      Sending message...")
            page.keyboard.press("Enter")
            page.wait_for_timeout(2000)

            log.info("      Message posted to Teams successfully!")
            return True

        except PlaywrightTimeout as e:
            log.error(f"      Timeout: {e}")
            return False
        except Exception as e:
            log.error(f"      Error: {e}")
            return False
        finally:
            page.wait_for_timeout(1500)
            context.close()
