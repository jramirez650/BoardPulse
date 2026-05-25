import os
import json
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

log = logging.getLogger("boardpulse")

TEAM_NAME    = os.getenv("TEAMS_TEAM_NAME", "")
CHANNEL_NAME = os.getenv("TEAMS_CHANNEL_NAME", "")
SESSION_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".teams_session")


def _write_clipboard(page, context, text: str):
    """Write text to clipboard, trying multiple methods."""
    try:
        context.grant_permissions(["clipboard-read", "clipboard-write"])
        page.evaluate(f"navigator.clipboard.writeText({json.dumps(text)})")
        return
    except Exception:
        pass
    # Fallback: write via execCommand (older API)
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


def _find_compose_box(page):
    """Try every known selector to locate the compose box, including Shadow DOM pierce."""
    selectors = [
        # Shadow DOM pierce (new Teams uses web components)
        "pierce/[aria-placeholder='Type a message']",
        "pierce/div[contenteditable='true']",
        "pierce/[role='textbox']",
        "pierce/[contenteditable='true']",
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
    for sel in selectors:
        try:
            els = page.locator(sel)
            count = els.count()
            if count > 0:
                el = els.last
                if el.is_visible(timeout=2000):
                    log.info(f"      Compose box found ({sel}, {count} match(es))")
                    return el
        except Exception:
            continue
    return None


def _focus_via_js(page) -> bool:
    """Walk the full Shadow DOM tree and focus the first visible contenteditable."""
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
                         el.getAttribute('role') ||
                         'element')
                    );
                }
            }
            // Recurse into shadow roots
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
        log.info(f"      JS Shadow DOM focus succeeded: {result}")
        return True
    log.warning("      JS Shadow DOM traversal found nothing")
    return False


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

            # ── Wait for Teams to load ────────────────────────────────────
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
                log.info("      Channel has posts — activating compose bar...")
                vp = page.viewport_size or {"width": 1280, "height": 720}
                page.mouse.click(vp["width"] // 2, vp["height"] - 80)
                page.wait_for_timeout(1500)
                log.info("      Compose bar mode — will use Enter to send")

            # ── 5. Focus compose box ──────────────────────────────────────
            log.info("      Locating compose box...")

            # First try keyboard shortcut — works even when element is in Shadow DOM
            log.info("      Trying Teams keyboard shortcut Alt+Shift+C...")
            page.keyboard.press("Alt+Shift+C")
            page.wait_for_timeout(1200)

            # Inspect what is currently focused
            focused_info = page.evaluate("""() => {
                const el = document.activeElement;
                if (!el || el === document.body) return 'body/none';
                return (
                    el.tagName + ':' +
                    (el.getAttribute('aria-label') ||
                     el.getAttribute('aria-placeholder') ||
                     el.id || 'no-label')
                );
            }""")
            log.info(f"      Active element after shortcut: {focused_info}")

            # Screenshot for debugging
            screenshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "teams_debug.png")
            page.screenshot(path=screenshot_path, full_page=False)
            log.info(f"      Screenshot saved: {screenshot_path}")

            # Try selector-based search (including pierce/ for Shadow DOM)
            compose_box = _find_compose_box(page)

            # ── 6. Paste message ──────────────────────────────────────────
            log.info("      Writing message to clipboard...")
            _write_clipboard(page, context, message)
            page.wait_for_timeout(400)

            if compose_box:
                log.info("      Clicking compose box and pasting...")
                compose_box.click()
                page.wait_for_timeout(500)
                page.keyboard.press("Control+a")
                page.keyboard.press("Control+v")
                page.wait_for_timeout(1000)

            elif "body" not in focused_info and focused_info != "body/none":
                # Alt+Shift+C focused something useful — paste directly
                log.info("      Compose box in focus (via shortcut) — pasting directly...")
                page.keyboard.press("Control+a")
                page.keyboard.press("Control+v")
                page.wait_for_timeout(1000)

            else:
                # Last resort: Shadow DOM JS traversal + paste
                log.info("      Trying JavaScript Shadow DOM traversal...")
                if _focus_via_js(page):
                    page.wait_for_timeout(600)
                    page.keyboard.press("Control+a")
                    page.keyboard.press("Control+v")
                    page.wait_for_timeout(1000)
                else:
                    # Log all contenteditable elements for diagnosis
                    all_ce = page.locator("[contenteditable]").all()
                    log.error(f"      Compose box not found. {len(all_ce)} contenteditable element(s) visible.")
                    for i, el in enumerate(all_ce):
                        try:
                            log.debug(f"        [{i}] tag={el.evaluate('e => e.tagName')} "
                                      f"aria={el.get_attribute('aria-label')} "
                                      f"role={el.get_attribute('role')} "
                                      f"visible={el.is_visible()}")
                        except Exception:
                            pass
                    raise Exception("Compose box not found — check teams_debug.png")

            # Screenshot after paste
            page.screenshot(
                path=screenshot_path.replace(".png", "_after_paste.png"),
                full_page=False,
            )
            log.info("      After-paste screenshot saved")

            # ── 7. Send ───────────────────────────────────────────────────
            # Try clicking the Teams send button (arrow icon) first — more
            # reliable than keyboard because it doesn't depend on focus.
            send_selectors = [
                "pierce/[data-tid='send-message-button']",
                "[data-tid='send-message-button']",
                "pierce/[aria-label='Send']",
                "[aria-label='Send']",
                "pierce/button[aria-label='Send message']",
                "button[aria-label='Send message']",
            ]
            if dialog_mode:
                send_selectors = ["button[aria-label='Post']", "pierce/button[aria-label='Post']"] + send_selectors

            sent = False
            for send_sel in send_selectors:
                try:
                    btn = page.locator(send_sel)
                    if btn.is_visible(timeout=1500):
                        btn.click()
                        sent = True
                        log.info(f"      Clicked send button ({send_sel})")
                        break
                except Exception:
                    continue

            if not sent:
                # Re-focus compose box, then use keyboard
                log.info("      Send button not found — re-focusing compose and pressing Enter...")
                if compose_box:
                    try:
                        compose_box.click()
                        page.wait_for_timeout(300)
                    except Exception:
                        pass
                else:
                    page.keyboard.press("Alt+Shift+C")
                    page.wait_for_timeout(500)

                if dialog_mode:
                    page.keyboard.press("Control+Enter")
                else:
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
