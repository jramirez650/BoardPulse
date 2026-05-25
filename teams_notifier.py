import os
import json
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

log = logging.getLogger("boardpulse")

TEAM_NAME    = os.getenv("TEAMS_TEAM_NAME", "")
CHANNEL_NAME = os.getenv("TEAMS_CHANNEL_NAME", "")
SESSION_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".teams_session")


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
            slow_mo=300,
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

            # ── 3. Click the team ─────────────────────────────────────────
            log.info(f"      Clicking team: '{TEAM_NAME}'")
            page.get_by_text(TEAM_NAME, exact=True).first.click()
            page.wait_for_timeout(1500)

            # ── 4. Click the channel ──────────────────────────────────────
            log.info(f"      Clicking channel: '{CHANNEL_NAME}'")
            page.get_by_text(CHANNEL_NAME, exact=True).first.click()
            page.wait_for_timeout(2000)

            # ── 5. Open compose dialog ────────────────────────────────────
            # Teams shows a "Publish in channel" button (text varies by language)
            # that opens a rich-text dialog with a "Post" button.
            log.info("      Opening compose dialog...")
            publish_btn_texts = [
                "Publicar en el canal",   # Spanish
                "Post in channel",        # English
                "Nueva publicación",
                "New post",
            ]
            dialog_opened = False
            for btn_text in publish_btn_texts:
                try:
                    btn = page.get_by_text(btn_text, exact=True)
                    if btn.is_visible(timeout=3000):
                        btn.click()
                        page.wait_for_timeout(2500)
                        dialog_opened = True
                        log.info(f"      Opened dialog via '{btn_text}'")
                        break
                except Exception:
                    continue

            if not dialog_opened:
                log.warning("      Compose dialog button not found — trying click at bottom of viewport...")
                vp = page.viewport_size or {"width": 1280, "height": 720}
                page.mouse.click(vp["width"] // 2, vp["height"] - 80)
                page.wait_for_timeout(1500)

            # ── 6. Find the message compose box ──────────────────────────
            log.info("      Looking for message compose box...")

            # Screenshot for debugging
            screenshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "teams_debug.png")
            page.screenshot(path=screenshot_path, full_page=False)
            log.info(f"      Debug screenshot saved: {screenshot_path}")

            selectors = [
                # Shadow DOM pierce selectors
                "pierce/[aria-placeholder='Type a message']",
                "pierce/div[contenteditable='true']",
                "pierce/[role='textbox']",
                # Standard selectors
                "[aria-placeholder='Type a message']",
                "p[data-placeholder='Type a message']",
                "[data-tid='ckeditor']",
                "[aria-label='Type a message']",
                "[aria-label='New message']",
                "div[contenteditable='true'][aria-multiline='true']",
                "div[contenteditable='true'][role='textbox']",
                ".ck-editor__editable",
                "[data-testid='message-texteditor-input']",
                "div[contenteditable='true']",
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
                # Try JS Shadow DOM traversal
                log.info("      Trying JavaScript Shadow DOM traversal to find compose box...")
                result = page.evaluate("""() => {
                    function findAndFocus(root) {
                        const candidates = root.querySelectorAll(
                            '[contenteditable="true"], [role="textbox"], [aria-placeholder]'
                        );
                        for (const el of candidates) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 50 && rect.height > 10) {
                                el.focus();
                                el.click();
                                return (
                                    el.tagName + ':' +
                                    (el.getAttribute('aria-placeholder') ||
                                     el.getAttribute('aria-label') ||
                                     el.getAttribute('role') || 'element')
                                );
                            }
                        }
                        for (const el of root.querySelectorAll('*')) {
                            if (el.shadowRoot) {
                                const found = findAndFocus(el.shadowRoot);
                                if (found) return found;
                            }
                        }
                        return null;
                    }
                    return findAndFocus(document);
                }""")
                if result:
                    log.info(f"      JS Shadow DOM found: {result}")
                else:
                    # Log all contenteditable for diagnosis
                    all_ce = page.locator("[contenteditable]").all()
                    log.error(f"      Compose box not found. {len(all_ce)} contenteditable element(s).")
                    for i, el in enumerate(all_ce):
                        try:
                            log.debug(f"        [{i}] tag={el.evaluate('e => e.tagName')} "
                                      f"aria={el.get_attribute('aria-label')} "
                                      f"role={el.get_attribute('role')} "
                                      f"visible={el.is_visible()}")
                        except Exception:
                            pass
                    raise Exception("Compose box not found — check teams_debug.png")

            # ── 7. Paste message ──────────────────────────────────────────
            log.info("      Pasting message...")
            _write_clipboard(page, context, message)
            page.wait_for_timeout(400)

            if compose_box:
                compose_box.click()
                page.wait_for_timeout(400)

            page.keyboard.press("Control+a")
            page.keyboard.press("Control+v")
            page.wait_for_timeout(1000)

            # After-paste screenshot
            page.screenshot(
                path=screenshot_path.replace(".png", "_after_paste.png"),
                full_page=False,
            )
            log.info("      After-paste screenshot saved")

            # ── 8. Send ───────────────────────────────────────────────────
            # Re-focus the compose box, then send with Ctrl+Enter.
            # Also try clicking the "Post" button as the primary method.
            log.info("      Sending message...")

            sent = False

            # Try the "Post" button first (most reliable in dialog mode)
            for post_sel in [
                "[data-tid='send-message-button']",
                "pierce/[data-tid='send-message-button']",
                "button[aria-label='Post']",
                "pierce/button[aria-label='Post']",
                "[aria-label='Send']",
                "pierce/[aria-label='Send']",
            ]:
                try:
                    btn = page.locator(post_sel)
                    if btn.is_visible(timeout=1500):
                        btn.click()
                        sent = True
                        log.info(f"      Clicked send button ({post_sel})")
                        break
                except Exception:
                    continue

            if not sent:
                # Re-focus and use Ctrl+Enter
                log.info("      Send button not found — using Ctrl+Enter...")
                if compose_box:
                    try:
                        compose_box.click()
                        page.wait_for_timeout(300)
                    except Exception:
                        pass
                page.keyboard.press("Control+Enter")

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
