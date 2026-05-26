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
            log.info("      Opening compose dialog...")

            # Ensure the browser tab is focused
            page.bring_to_front()
            page.wait_for_timeout(500)

            screenshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "teams_debug.png")

            def _dom_state(label: str):
                """Log relevant DOM state for diagnostics."""
                try:
                    s = page.evaluate("""() => {
                        const tids = [...new Set(
                            Array.from(document.querySelectorAll('[data-tid]'))
                                 .map(e => e.getAttribute('data-tid')).filter(Boolean)
                        )];
                        const ces = document.querySelectorAll('[contenteditable]').length;
                        return {ces, tids};
                    }""")
                    log.debug(f"      DOM [{label}]: CE={s['ces']}  tids={s['tids']}")
                except Exception:
                    pass

            _dom_state("before-compose-click")
            page.screenshot(path=screenshot_path.replace(".png", "_1_before.png"), full_page=False)

            # Primary: click compose-start-post (language-independent data-tid)
            dialog_opened = False
            try:
                btn = page.locator("[data-tid='compose-start-post']")
                count = btn.count()
                log.info(f"      Found {count} compose-start-post button(s)")
                if count > 0:
                    # Force-click bypasses any transparency/overlay that would block a normal click
                    btn.first.scroll_into_view_if_needed()
                    btn.first.click(force=True)
                    dialog_opened = True
                    log.info("      Clicked [data-tid='compose-start-post'] (force=True)")
            except Exception as e:
                log.debug(f"      compose-start-post click failed: {e}")

            # Fallback: button text variants
            if not dialog_opened:
                for btn_text in ["Publicar en el canal", "Post in channel", "Nueva publicación", "New post"]:
                    try:
                        btn = page.get_by_text(btn_text, exact=True)
                        if btn.is_visible(timeout=2000):
                            btn.click(force=True)
                            dialog_opened = True
                            log.info(f"      Opened dialog via text '{btn_text}'")
                            break
                    except Exception:
                        continue

            if not dialog_opened:
                log.warning("      Compose button not found — clicking bottom-center of viewport...")
                vp = page.viewport_size or {"width": 1280, "height": 720}
                page.mouse.click(vp["width"] // 2, vp["height"] - 100)

            page.wait_for_timeout(1000)
            page.screenshot(path=screenshot_path.replace(".png", "_2_after_click.png"), full_page=False)
            _dom_state("after-compose-click")

            # ── 6. Wait for compose container, then find editor ───────────
            # The CKEditor lives inside the Shadow DOM of post-compose-layout.
            # Regular document.querySelector cannot see it — we need either
            # evaluate_handle (JS shadow traversal) or coordinate-based click.
            log.info("      Waiting for compose container (post-compose-layout)...")
            compose_container_found = False
            for attempt in range(12):          # up to ~24 s
                page.wait_for_timeout(2000)
                count = page.locator("[data-tid='post-compose-layout']").count()
                log.info(f"      [{attempt+1}/12] post-compose-layout count={count}")
                if count > 0:
                    compose_container_found = True
                    log.info("      Compose container ready.")
                    break

            page.screenshot(path=screenshot_path, full_page=False)
            log.info(f"      Debug screenshot: {screenshot_path}")

            if not compose_container_found:
                raise Exception("post-compose-layout never appeared — compose did not open")

            # Extra settle time for CKEditor to initialize inside the shadow root
            page.wait_for_timeout(2000)

            # ── Shadow-DOM traversal to get an ElementHandle ──────────────
            _SHADOW_FINDER = """() => {
                function findInShadow(root) {
                    const el = root.querySelector('[data-tid="ckeditor"]')
                             || root.querySelector('[contenteditable="true"][role="textbox"]')
                             || root.querySelector('[contenteditable="true"]');
                    if (el) return el;
                    for (const node of root.querySelectorAll('*')) {
                        if (node.shadowRoot) {
                            const found = findInShadow(node.shadowRoot);
                            if (found) return found;
                        }
                    }
                    return null;
                }
                return findInShadow(document);
            }"""

            compose_handle = page.evaluate_handle(_SHADOW_FINDER)
            compose_box = compose_handle.as_element()   # ElementHandle or None

            if compose_box:
                log.info("      CKEditor found via shadow-DOM traversal.")
            else:
                # Coordinate fallback: click in the body area of the compose container
                log.warning("      Shadow-DOM traversal returned nothing — using coordinate click.")
                container = page.locator("[data-tid='post-compose-layout']")
                box = container.bounding_box()
                if box:
                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] * 0.65   # below subject line
                    page.mouse.click(cx, cy)
                    log.info(f"      Clicked compose area at ({cx:.0f}, {cy:.0f})")
                    page.wait_for_timeout(600)
                    # Try shadow traversal one more time after click
                    compose_handle = page.evaluate_handle(_SHADOW_FINDER)
                    compose_box = compose_handle.as_element()
                    if compose_box:
                        log.info("      CKEditor found on second shadow-DOM attempt.")
                    else:
                        log.warning("      Proceeding without CKEditor handle (keyboard-only mode).")

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
            log.info("      Sending message...")
            sent = False

            # Try shadow-DOM traversal to find the Post button
            _POST_BTN_FINDER = """() => {
                function findInShadow(root) {
                    const btn = root.querySelector('[data-tid="post"] button')
                              || root.querySelector('[data-tid="post-button"]')
                              || root.querySelector('[data-tid="send-message-button"]');
                    if (btn) return btn;
                    for (const node of root.querySelectorAll('*')) {
                        if (node.shadowRoot) {
                            const found = findInShadow(node.shadowRoot);
                            if (found) return found;
                        }
                    }
                    return null;
                }
                return findInShadow(document);
            }"""
            try:
                post_handle = page.evaluate_handle(_POST_BTN_FINDER)
                post_btn = post_handle.as_element()
                if post_btn:
                    post_btn.click()
                    sent = True
                    log.info("      Clicked Post button via shadow-DOM traversal")
            except Exception as e:
                log.debug(f"      Shadow-DOM post button search failed: {e}")

            # Fallback: Playwright locator (may also pierce shadow DOM)
            if not sent:
                for post_sel in ["[data-tid='post'] button", "[data-tid='post-button']"]:
                    try:
                        btn = page.locator(post_sel)
                        if btn.count() > 0:
                            btn.first.click(force=True)
                            sent = True
                            log.info(f"      Clicked send button ({post_sel})")
                            break
                    except Exception:
                        continue

            # Fallback: button by visible text
            if not sent:
                for btn_text in ["Publicar", "Post", "Send", "Enviar"]:
                    try:
                        btn = page.get_by_role("button", name=btn_text, exact=True)
                        if btn.count() > 0:
                            btn.first.click(force=True)
                            sent = True
                            log.info(f"      Clicked '{btn_text}' button")
                            break
                    except Exception:
                        continue

            # Last resort: Ctrl+Enter keyboard shortcut
            if not sent:
                log.info("      Send button not found — using Ctrl+Enter...")
                if compose_box:
                    compose_box.click()
                    page.wait_for_timeout(300)
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
