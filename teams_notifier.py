import os
import json
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

log = logging.getLogger("boardpulse")

TEAM_NAME    = os.getenv("TEAMS_TEAM_NAME", "")
CHANNEL_NAME = os.getenv("TEAMS_CHANNEL_NAME", "")
SESSION_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".teams_session")

# Saved channel URL — set once, reused on every run to skip Teams loading time
_CHANNEL_URL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".teams_channel_url")

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
        log.info(f"      Launching browser (session: {SESSION_DIR})")

        context = p.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR,
            headless=False,
            slow_mo=0,                  # removed — saves ~10 s per run
            args=["--start-maximized"],
            no_viewport=True,
        )

        page = context.pages[0] if context.pages else context.new_page()

        try:
            def _is_teams_url(url):
                return "teams.cloud.microsoft" in url or "teams.microsoft.com" in url

            # ── 1. Navigate ───────────────────────────────────────────────
            # Fast path: go straight to the saved channel URL (skips ~60 s of
            # Teams loading + team/channel clicking on every subsequent run).
            saved_url = None
            if os.path.exists(_CHANNEL_URL_FILE):
                saved_url = open(_CHANNEL_URL_FILE).read().strip()

            if saved_url:
                log.info(f"      Navigating directly to channel URL...")
                page.goto(saved_url, wait_until="domcontentloaded", timeout=30000)
            else:
                log.info("      No saved channel URL — doing full navigation...")
                page.goto("https://teams.cloud.microsoft", wait_until="domcontentloaded", timeout=30000)

            page.wait_for_timeout(2000)

            # Handle login if needed
            if not _is_teams_url(page.url) or "login" in page.url.lower():
                log.info("      Login required — please sign in...")
                print("\n   🔐 Please log in to Teams in the browser window.\n"
                      "      Waiting up to 3 minutes...\n")
                page.wait_for_url(_is_teams_url, timeout=180000)
                page.wait_for_timeout(3000)

            # ── 2. Wait for Teams to be ready ─────────────────────────────
            log.info("      Waiting for Teams to load...")
            for selector in ['[data-tid="leftRail"]', '[data-tid="app-bar"]',
                             'nav[aria-label]', '#app-mount']:
                try:
                    page.wait_for_selector(selector, timeout=60000)
                    log.info(f"      Teams ready ({selector})")
                    break
                except Exception:
                    continue

            page.bring_to_front()

            # ── 3. Navigate to team + channel (only if no saved URL) ──────
            if not saved_url:
                log.info(f"      Clicking team: '{TEAM_NAME}'")
                page.get_by_text(TEAM_NAME, exact=True).first.click()
                page.wait_for_timeout(1000)

                log.info(f"      Clicking channel: '{CHANNEL_NAME}'")
                page.get_by_text(CHANNEL_NAME, exact=True).first.click()
                page.wait_for_timeout(1500)

                # Save the channel URL for future fast-path runs
                channel_url = page.url
                if _is_teams_url(channel_url) and "login" not in channel_url:
                    open(_CHANNEL_URL_FILE, "w").write(channel_url)
                    log.info(f"      Channel URL saved for next run: {channel_url}")

            # ── 4. Click "Post in channel" (up to 4 retries) ─────────────
            log.info("      Clicking 'Post in channel' button...")
            compose_opened = False
            for attempt in range(1, 5):
                page.locator("[data-tid='compose-start-post']").click(force=True)
                log.info(f"      Clicked (attempt {attempt}) — checking if compose opened...")
                try:
                    page.locator(_XP_TEXT_FIELD).wait_for(state="visible", timeout=4000)
                    compose_opened = True
                    log.info(f"      Compose opened on attempt {attempt}")
                    break
                except Exception:
                    log.warning(f"      Compose not open yet, retrying ({attempt}/4)...")
                    page.wait_for_timeout(800)

            if not compose_opened:
                raise Exception("Compose did not open after 4 click attempts")

            # ── 5. Click text field & paste ───────────────────────────────
            log.info("      Pasting message...")
            page.locator(_XP_TEXT_FIELD).click()
            page.wait_for_timeout(300)

            _write_clipboard(page, context, message)
            page.wait_for_timeout(300)
            page.keyboard.press("Control+a")
            page.keyboard.press("Control+v")
            page.wait_for_timeout(800)

            # ── 6. Click Post ─────────────────────────────────────────────
            log.info("      Clicking Post button...")
            post_btn = page.locator(_XP_POST_BUTTON)
            post_btn.wait_for(state="visible", timeout=10000)
            post_btn.click()

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
            page.wait_for_timeout(1000)
            context.close()
