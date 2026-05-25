import sys
import io
import logging
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from jira_client import get_sprint_tickets
from rules import detect_stale_tickets, detect_po_accepted
from ai_summarizer import generate_alert
from teams_notifier import send_to_teams

# ── Logging setup ─────────────────────────────────────────────────────────────
LOG_FILE = f"boardpulse_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),          # console
        logging.FileHandler(LOG_FILE, encoding="utf-8"),  # file
    ],
)
log = logging.getLogger("boardpulse")
# ──────────────────────────────────────────────────────────────────────────────


def run():
    log.info("=" * 60)
    log.info("BoardPulse starting")
    log.info("=" * 60)

    # 1. Fetch sprint tickets
    log.info("[1/4] Connecting to Jira and fetching sprint tickets...")
    try:
        issues = get_sprint_tickets()
        log.info(f"      OK — found {len(issues)} tickets in the active sprint")
    except Exception as e:
        log.error(f"      FAILED to fetch tickets: {e}")
        return

    # 2. Apply detection rules
    log.info("[2/4] Running detection rules...")
    try:
        stale = detect_stale_tickets(issues)
        po_accepted = detect_po_accepted(issues)
        log.info(f"      Stale tickets detected    : {len(stale)}")
        log.info(f"      PO-accepted tickets found : {len(po_accepted)}")
        if stale:
            for t in stale:
                log.debug(f"        STALE  {t['key']} — {t['days_stale']}d — {t['status']} — {t['assignee']}")
        if po_accepted:
            for t in po_accepted:
                log.debug(f"        PO-ACC {t['key']} — {t['assignee']} — {t['transition_date']}")
    except Exception as e:
        log.error(f"      FAILED during rule detection: {e}")
        return

    if not stale and not po_accepted:
        log.info("      All clear — nothing to report.")
        return

    # 3. Generate AI alert
    log.info("[3/4] Sending data to OpenAI for summary generation...")
    try:
        alert_message = generate_alert(stale, po_accepted)
        log.info("      AI summary generated successfully")
        log.debug(f"\n{alert_message}")
    except Exception as e:
        log.error(f"      FAILED to generate AI summary: {e}")
        return

    print(f"\n{'─'*60}\n{alert_message}\n{'─'*60}\n")

    # 4. Send to Teams
    log.info("[4/4] Sending alert to Microsoft Teams...")
    try:
        success = send_to_teams(alert_message)
        if success:
            log.info("      Message sent to Teams successfully")
        else:
            log.warning("      Teams returned a non-success status code")
    except Exception as e:
        log.error(f"      FAILED to send to Teams: {e}")
        return

    log.info("BoardPulse finished")
    log.info(f"Log saved to: {LOG_FILE}")


if __name__ == "__main__":
    run()
