from jira_client import get_sprint_tickets
from rules import detect_stale_tickets, detect_po_accepted
from ai_summarizer import generate_alert
from teams_notifier import send_to_teams


def run():
    print("🔍 BoardPulse - Scanning board...")

    # 1. Fetch sprint tickets
    issues = get_sprint_tickets()
    print(f"   Found {len(issues)} tickets in the active sprint")

    # 2. Apply detection rules
    stale = detect_stale_tickets(issues)
    po_accepted = detect_po_accepted(issues)
    print(f"   🚨 Stale tickets: {len(stale)}")
    print(f"   ✅ PO-accepted tickets: {len(po_accepted)}")

    if not stale and not po_accepted:
        print("   ✨ All clear, nothing to report!")
        return

    # 3. Generate AI alert
    print("   🤖 Generating AI summary...")
    alert_message = generate_alert(stale, po_accepted)
    print(f"\n{alert_message}\n")

    # 4. Send to Teams
    print("   📤 Sending to Teams...")
    success = send_to_teams(alert_message)
    if success:
        print("   ✅ Message sent successfully!")
    else:
        print("   ❌ Error sending to Teams")


if __name__ == "__main__":
    run()
