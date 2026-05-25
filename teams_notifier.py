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
            dialog_opened = False

            # Primary: stable data-tid attribute (language-independent)
            try:
                btn = page.locator("[data-tid='compose-start-post']")
                if btn.is_visible(timeout=4000):
                    btn.click()
                    page.wait_for_timeout(3000)
                    dialog_opened = True
                    log.info("      Opened dialog via [data-tid='compose-start-post']")
            except Exception:
                pass

            # Fallback: button text (varies by Teams UI language)
            if not dialog_opened:
                for btn_text in ["Publicar en el canal", "Post in channel", "Nueva publicación", "New post"]:
                    try:
                        btn = page.get_by_text(btn_text, exact=True)
                        if btn.is_visible(timeout=2000):
                            btn.click()
                            page.wait_for_timeout(3000)
                            dialog_opened = True
                            log.info(f"      Opened dialog via text '{btn_text}'")
                            break
                    except Exception:
                        continue

            if not dialog_opened:
                log.warning("      Compose dialog button not found — trying click at bottom of viewport...")
                vp = page.viewport_size or {"width": 1280, "height": 720}
                page.mouse.click(vp["width"] // 2, vp["height"] - 80)
                page.wait_for_timeout(1500)

            # Extra wait for the dialog's rich-text editor to fully render
            page.wait_for_timeout(3000)

            # ── 6. Find the message compose box ──────────────────────────
            log.info("      Looking for message compose box...")

            # Screenshot for debugging
            screenshot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "teams_debug.png")
            page.screenshot(path=screenshot_path, full_page=False)
            log.info(f"      Debug screenshot saved: {screenshot_path}")

            # Confirmed selectors from live DOM inspection (in order of preference)
            compose_selectors = [
                "[data-tid='ckeditor']",                        # most stable, language-independent
                "[aria-label='Escriba un mensaje']",            # Spanish UI (confirmed)
                "[aria-label='Type a message']",                # English UI
                "[aria-label='New message']",
                "div[contenteditable='true'][role='textbox']",  # generic fallback
                "div[contenteditable='true']",                  # last resort
            ]

            compose_box = None
            found_sel = None

            # Primary: search the main page directly (confirmed in DOM — not inside an iframe)
            for sel in compose_selectors:
                try:
                    els = page.locator(sel)
                    if els.count() > 0:
                        el = els.last
                        if el.is_visible(timeout=2000):
                            compose_box = el
                            found_sel = sel
                            log.info(f"      Compose box found via '{sel}'")
                            break
                except Exception:
                    continue

            # Fallback: check child iframes (rare but possible in some Teams versions)
            if not compose_box and len(page.frames) > 1:
                log.info(f"      Not found in main frame — checking {len(page.frames)-1} child frame(s)...")
                for frame in page.frames[1:]:
                    url_snippet = frame.url[:80] if frame.url else "(no url)"
                    for sel in compose_selectors:
                        try:
                            els = frame.locator(sel)
                            if els.count() > 0:
                                el = els.last
                                if el.is_visible(timeout=1500):
                                    compose_box = el
                                    found_sel = sel
                                    log.info(f"      Compose box found in frame [{url_snippet}] via '{sel}'")
                                    break
                        except Exception:
                            continue
                    if compose_box:
                        break

            if not compose_box:
                log.error("      Compose box not found.")
                for frame in page.frames:
                    try:
                        count = frame.locator("[contenteditable]").count()
                        log.debug(f"        frame={frame.url[:60]}  contenteditable={count}")
                    except Exception:
                        pass
                raise Exception("Compose box not found — check teams_debug.png")

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
