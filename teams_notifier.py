import os
import json
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

log = logging.getLogger("boardpulse")

TEAM_NAME    = os.getenv("TEAMS_TEAM_NAME", "")
CHANNEL_NAME = os.getenv("TEAMS_CHANNEL_NAME", "")
SESSION_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".teams_session")

# Confirmed XPaths from live DOM inspection
_XP_POST_IN_CHANNEL = "xpath=/html/body/div[1]/div/div/div/div[9]/div/div[1]/div/div[3]/div/div/button"
_XP_TEXT_FIELD      = "xpath=/html/body/div[1]/div/div/div/div[9]/div/div[1]/div/div[3]/div/div/div/div/div[1]/div/div/div[4]/div[1]"
_XP_POST_BUTTON     = "xpath=/html/body/div[1]/div/div/div/div[9]/div/div[1]/div/div[3]/div/div/div/div/div[1]/div/div/div[5]/div/div[2]/div/button"


def _write_clipboard(page, context, text: str):
    """Write text to clipboard, with execCommand fallback."""
    try:
        context.grant_permissions(["clipboard-read", "clipboard-write"])
        page.evaluate(f"navigator.clipboard.writeText({json.dumps(text)})")
        return
    except Exception:
        pass
    try:
        page.evaluate(f"""() => {{
            const ta = document.createElement('textarea');
            ta.value = {json.dumps(text)};
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        }}""")
    except Exception as e:
        log.warning(f"      clipboard write fallback also failed: {e}")


def send_to_teams(message: str) -> bool:
    with sync_playwright() as p:
        log.info(f"      Launching browser (session saved at: {SESSION_DIR})")

        context = p.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR,
            headless=False,
            slow_mo=200,
            args=["--start-maximized"],
            no_viewport=True,
        )

        page = context.pages[0] if context.pages else context.new_page()

        try:
            # ── 1. Navigate to Teams ──────────────────────────────────────
            log.info("      Navigating to Microsoft Teams...")
            page.goto("https://teams.cloud.microsoft", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            def _is_teams_url(url):
                return "teams.cloud.microsoft" in url or "teams.microsoft.com" in url

            if not _is_teams_url(page.url) or "login" in page.url.lower():
                log.info("      Login page detected — please sign in with your Okta account...")
                print("\n   🔐 Please log in to Teams in the browser window that just opened.\n"
                      "      Waiting up to 3 minutes...\n")
                page.wait_for_url(_is_teams_url, timeout=180000)
                page.wait_for_timeout(4000)

            # ── 2. Wait for Teams to load ─────────────────────────────────
            log.info("      Waiting for Teams to fully load...")
            for selector in [
                '[data-tid="leftRail"]',
                '[data-tid="app-bar"]',
                'nav[aria-label]',
                '[class*="appMount"]',
                '#app-mount',
            ]:
                try:
                    page.wait_for_selector(selector, timeout=15000)
                    log.info(f"      Teams loaded ({selector})")
                    break
                except Exception:
                    continue

            page.wait_for_timeout(2000)
            page.bring_to_front()

            # ── 3. Click the team ─────────────────────────────────────────
            log.info(f"      Clicking team: '{TEAM_NAME}'")
            page.get_by_text(TEAM_NAME, exact=True).first.click()
            page.wait_for_timeout(1500)

            # ── 4. Click the channel ──────────────────────────────────────
            log.info(f"      Clicking channel: '{CHANNEL_NAME}'")
            page.get_by_text(CHANNEL_NAME, exact=True).first.click()
            page.wait_for_timeout(2000)

            # ── 5. Click "Post in channel" button (up to 4 retries) ──────────
            log.info("      Clicking 'Post in channel' button...")
            for attempt in range(1, 5):
                try:
                    page.locator("[data-tid='compose-start-post']").click(force=True)
                    log.info(f"      Clicked (attempt {attempt})")
                    break
                except Exception as e:
                    log.warning(f"      Attempt {attempt} failed: {e}")
                    page.wait_for_timeout(1000)
            page.wait_for_timeout(2000)

            # ── 6. Wait for text field and click it ───────────────────────
            log.info("      Waiting for compose text field...")
            text_field = page.locator(_XP_TEXT_FIELD)
            text_field.wait_for(state="visible", timeout=15000)
            text_field.click()
            log.info("      Compose text field ready")
            page.wait_for_timeout(400)

            # ── 7. Paste message ──────────────────────────────────────────
            log.info("      Pasting message...")
            _write_clipboard(page, context, message)
            page.wait_for_timeout(400)
            page.keyboard.press("Control+a")
            page.keyboard.press("Control+v")
            page.wait_for_timeout(1000)

            # Debug screenshot after paste
            screenshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "teams_debug.png")
            page.screenshot(path=screenshot_path, full_page=False)
            log.info(f"      After-paste screenshot: {screenshot_path}")

            # ── 8. Click the Post button ──────────────────────────────────
            log.info("      Clicking Post button...")
            post_btn = page.locator(_XP_POST_BUTTON)
            post_btn.wait_for(state="visible", timeout=10000)
            post_btn.click()
            log.info("      Post button clicked")

            page.wait_for_timeout(2500)
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
