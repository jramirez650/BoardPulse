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
            page.goto("https://teams.cloud.microsoft", wait_until="domcontentloaded", timeout=30000)

            # Wait for login/redirect to settle
            page.wait_for_timeout(3000)

            # If redirected to Okta/login, wait up to 3 min for manual login
            def _is_teams_url(url):
                return "teams.cloud.microsoft" in url or "teams.microsoft.com" in url

            if not _is_teams_url(page.url) or "login" in page.url.lower():
                log.info("      Login page detected — please sign in with your Okta account...")
                print("\n   🔐 Please log in to Teams in the browser window that just opened.\n"
                      "      Waiting up to 3 minutes...\n")
                page.wait_for_url(_is_teams_url, timeout=180000)
                page.wait_for_timeout(4000)

            # Wait for Teams app to finish loading (try multiple selectors)
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

            # ── 2. Click the team ─────────────────────────────────────────
            log.info(f"      Clicking team: '{TEAM_NAME}'")
            page.get_by_text(TEAM_NAME, exact=True).first.click()
            page.wait_for_timeout(1500)

            # ── 3. Click the channel ──────────────────────────────────────
            log.info(f"      Clicking channel: '{CHANNEL_NAME}'")
            page.get_by_text(CHANNEL_NAME, exact=True).first.click()
            page.wait_for_timeout(1500)

            # ── 4. Activate compose area ──────────────────────────────────
            dialog_mode = False
            try:
                post_btn = page.get_by_text("Post in channel", exact=True)
                if post_btn.is_visible(timeout=3000):
                    log.info("      Clicking 'Post in channel' button (empty channel)...")
                    post_btn.click()
                    page.wait_for_timeout(2000)
                    dialog_mode = True
                    log.info("      Dialog mode — will use Post button to send")
            except Exception:
                # Channel has posts — click bottom of viewport to activate compose bar
                log.info("      Channel has posts — activating compose bar...")
                vp = page.viewport_size or {"width": 1280, "height": 720}
                page.mouse.click(vp["width"] // 2, vp["height"] - 80)
                page.wait_for_timeout(1500)
                log.info("      Compose bar mode — will use Enter to send")

            # ── 5. Find compose box ───────────────────────────────────────
            log.info("      Looking for message compose box...")

            # Screenshot taken AFTER compose activation
            screenshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "teams_debug.png")
            page.screenshot(path=screenshot_path, full_page=False)
            log.info(f"      Screenshot saved: {screenshot_path}")

            selectors = [
                '[aria-placeholder="Type a message"]',
                'p[data-placeholder="Type a message"]',
                '[data-tid="ckeditor"]',
                '[aria-label="Type a message"]',
                '[aria-label="New message"]',
                'div[contenteditable="true"][aria-multiline="true"]',
                'div[contenteditable="true"][role="textbox"]',
                '.ck-editor__editable',
                '[data-testid="message-texteditor-input"]',
                'div[contenteditable="true"]',
            ]

            compose_box = None
            for sel in selectors:
                try:
                    els = page.locator(sel)
                    count = els.count()
                    if count > 0:
                        el = els.last
                        if el.is_visible(timeout=2000):
                            compose_box = el
                            log.info(f"      Compose box found ({sel}, {count} match(es))")
                            break
                except Exception:
                    continue

            if not compose_box:
                # Last resort: find all contenteditable elements and log them
                all_ce = page.locator('[contenteditable]').all()
                log.error(f"      Compose box not found. Found {len(all_ce)} contenteditable elements.")
                for i, el in enumerate(all_ce):
                    try:
                        log.debug(f"        [{i}] tag={el.evaluate('e => e.tagName')} "
                                  f"aria={el.get_attribute('aria-label')} "
                                  f"role={el.get_attribute('role')} "
                                  f"visible={el.is_visible()}")
                    except Exception:
                        pass
                raise Exception("Compose box not found — check teams_debug.png")

            # ── 6. Paste message via clipboard ────────────────────────────
            log.info("      Pasting message...")
            context.grant_permissions(["clipboard-read", "clipboard-write"])
            page.evaluate(f"navigator.clipboard.writeText({json.dumps(message)})")
            compose_box.click()
            page.wait_for_timeout(500)
            page.keyboard.press("Control+a")
            page.keyboard.press("Control+v")
            page.wait_for_timeout(1000)

            # ── 7. Send ───────────────────────────────────────────────────
            if dialog_mode:
                # Dialog (empty channel): click the "Post" button
                log.info("      Clicking Post button...")
                try:
                    send_btn = page.get_by_role("button", name="Post")
                    if not send_btn.is_visible(timeout=2000):
                        raise Exception("Post button not visible")
                    send_btn.click()
                except Exception:
                    log.info("      Post button not found, trying Ctrl+Enter...")
                    page.keyboard.press("Control+Enter")
            else:
                # Compose bar (channel has posts): Enter sends
                log.info("      Pressing Enter to send...")
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
