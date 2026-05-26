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

            # ── 6. Find the message compose box ──────────────────────────
            # Poll via JS (more reliable than wait_for_selector with slow_mo)
            log.info("      Polling for compose editor (up to 20 s)...")

            compose_box = None
            found_sel = None

            for attempt in range(10):
                page.wait_for_timeout(2000)

                check = page.evaluate("""() => {
                    const ed = document.querySelector('[data-tid="ckeditor"]');
                    if (ed) {
                        const r = ed.getBoundingClientRect();
                        return {found: true, w: r.width, h: r.height, top: r.top,
                                ce: ed.getAttribute('contenteditable')};
                    }
                    const ces = Array.from(document.querySelectorAll('[contenteditable]'))
                        .map(e => e.tagName + '[' + e.getAttribute('contenteditable') + ']');
                    const tids = [...new Set(
                        Array.from(document.querySelectorAll('[data-tid]'))
                             .map(e => e.getAttribute('data-tid')).filter(Boolean)
                    )];
                    return {found: false, ces, tids};
                }""")
                log.info(f"      [{attempt+1}/10] JS check: {check}")

                if check.get('found'):
                    if check.get('w', 0) > 0 and check.get('h', 0) > 0:
                        # Element visible — use it directly
                        compose_box = page.locator("[data-tid='ckeditor']").last
                        found_sel = "[data-tid='ckeditor']"
                        log.info("      Compose editor is visible — ready to type!")
                        break
                    else:
                        # In DOM but zero-size — scroll it into view and retry once
                        log.info("      CKEditor found but zero-size — scrolling into view...")
                        try:
                            page.locator("[data-tid='ckeditor']").last.scroll_into_view_if_needed()
                            page.wait_for_timeout(800)
                        except Exception:
                            pass

            # Take the main debug screenshot after polling
            page.screenshot(path=screenshot_path, full_page=False)
            log.info(f"      Debug screenshot: {screenshot_path}")

            # Fallback selectors if JS polling didn't find [data-tid='ckeditor']
            if not compose_box:
                for sel in [
                    "[aria-label='Escriba un mensaje']",
                    "[aria-label='Type a message']",
                    "div[contenteditable='true'][role='textbox']",
                    "div[contenteditable='true']",
                ]:
                    try:
                        els = page.locator(sel)
                        if els.count() > 0 and els.last.is_visible(timeout=1000):
                            compose_box = els.last
                            found_sel = sel
                            log.info(f"      Compose box found via fallback selector '{sel}'")
                            break
                    except Exception:
                        continue

            # Last resort: check child iframes
            if not compose_box and len(page.frames) > 1:
                for frame in page.frames[1:]:
                    for sel in ["[data-tid='ckeditor']", "div[contenteditable='true']"]:
                        try:
                            els = frame.locator(sel)
                            if els.count() > 0 and els.last.is_visible(timeout=1000):
                                compose_box = els.last
                                found_sel = f"iframe > {sel}"
                                log.info(f"      Compose box in iframe via '{sel}'")
                                break
                        except Exception:
                            continue
                    if compose_box:
                        break

            if not compose_box:
                raise Exception("Compose box not found after 20 s — check teams_debug*.png")

            # ── 7. Paste message ──────────────────────────────────────────
            log.info("      Pasting message...")
            _write_clipboard(page, context, message)
            page.wait_for_timeout(400)

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

            # Confirmed from live DOM: send button is inside [data-tid='post']
            # <div data-tid="post"><button type="button">Publicar</button></div>
            send_selectors = [
                "[data-tid='post'] button",   # confirmed in DOM (primary)
                "[data-tid='post-button']",
                "[data-tid='send-message-button']",
            ]
            for post_sel in send_selectors:
                try:
                    btn = page.locator(post_sel)
                    if btn.is_visible(timeout=1500):
                        btn.click()
                        sent = True
                        log.info(f"      Clicked send button ({post_sel})")
                        break
                except Exception:
                    continue

            # Fallback: by button role + text
            if not sent:
                for btn_text in ["Publicar", "Post", "Send", "Enviar"]:
                    try:
                        btn = page.get_by_role("button", name=btn_text, exact=True)
                        if btn.is_visible(timeout=1000):
                            btn.click()
                            sent = True
                            log.info(f"      Clicked '{btn_text}' button")
                            break
                    except Exception:
                        continue

            # Last resort: Ctrl+Enter keyboard shortcut
            if not sent:
                log.info("      Send button not found — re-focusing and using Ctrl+Enter...")
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
