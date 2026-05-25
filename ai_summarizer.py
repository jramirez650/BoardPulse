from openai import OpenAI
from config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)


def generate_alert(stale_tickets, po_accepted_tickets):
    ticket_data = f"""
Stale tickets (no movement):
{stale_tickets}

Recently PO-accepted tickets (ready to move forward):
{po_accepted_tickets}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are BoardPulse, an assistant for development managers. "
                    "Your job is to generate a clear and actionable summary of the board status.\n\n"
                    "Rules:\n"
                    "- Be direct and concise\n"
                    "- Classify each situation as HIGH, MEDIUM, or LOW urgency\n"
                    "- For stale tickets: mention the ticket, who owns it, "
                    "how many days it has been stuck, and suggest an action\n"
                    "- For PO-accepted tickets: mention they are ready to move forward "
                    "and who should pick them up\n"
                    "- Use emojis to make it easy to scan in Teams\n"
                    "- End with a one-line summary of the overall sprint health"
                ),
            },
            {
                "role": "user",
                "content": f"Generate the BoardPulse report with this data:\n{ticket_data}",
            },
        ],
        max_tokens=1000,
    )

    return response.choices[0].message.content
