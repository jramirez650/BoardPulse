from openai import OpenAI
from config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)


def generate_alert(stale_tickets, po_accepted_tickets):
    ticket_data = f"""
Tickets estancados (sin movimiento):
{stale_tickets}

Tickets recién aceptados por PO (listos para avanzar):
{po_accepted_tickets}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "Sos BoardPulse, un asistente para managers de desarrollo. "
                    "Tu trabajo es generar un resumen claro y accionable del estado del board.\n\n"
                    "Reglas:\n"
                    "- Sé directo y conciso\n"
                    "- Clasificá cada situación como urgencia ALTA, MEDIA o BAJA\n"
                    "- Para tickets estancados: mencioná el ticket, quién lo tiene, "
                    "hace cuántos días y sugerí acción\n"
                    "- Para tickets aceptados por PO: mencioná que están listos para avanzar "
                    "y quién debe tomarlos\n"
                    "- Usá emojis para que sea fácil de escanear en Teams\n"
                    "- Terminá con un resumen de una línea del estado general del sprint"
                ),
            },
            {
                "role": "user",
                "content": f"Generá el reporte de BoardPulse con estos datos:\n{ticket_data}",
            },
        ],
        max_tokens=1000,
    )

    return response.choices[0].message.content
