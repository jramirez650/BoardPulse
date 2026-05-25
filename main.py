from jira_client import get_sprint_tickets
from rules import detect_stale_tickets, detect_po_accepted
from ai_summarizer import generate_alert
from teams_notifier import send_to_teams


def run():
    print("🔍 BoardPulse - Escaneando board...")

    # 1. Fetch sprint tickets
    issues = get_sprint_tickets()
    print(f"   Encontrados {len(issues)} tickets en el sprint activo")

    # 2. Apply detection rules
    stale = detect_stale_tickets(issues)
    po_accepted = detect_po_accepted(issues)
    print(f"   🚨 Tickets estancados: {len(stale)}")
    print(f"   ✅ Tickets aceptados por PO: {len(po_accepted)}")

    if not stale and not po_accepted:
        print("   ✨ Todo limpio, nada que reportar!")
        return

    # 3. Generate AI alert
    print("   🤖 Generando resumen con AI...")
    alert_message = generate_alert(stale, po_accepted)
    print(f"\n{alert_message}\n")

    # 4. Send to Teams
    print("   📤 Enviando a Teams...")
    success = send_to_teams(alert_message)
    if success:
        print("   ✅ Mensaje enviado exitosamente!")
    else:
        print("   ❌ Error enviando a Teams")


if __name__ == "__main__":
    run()
