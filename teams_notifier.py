import requests
from config import TEAMS_WEBHOOK_URL


def send_to_teams(message):
    # Power Automate (Workflows) replaced the deprecated Teams Incoming Webhooks.
    # The new payload wraps the message inside an "attachments" card body.
    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.2",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": message,
                            "wrap": True,
                        }
                    ],
                },
            }
        ],
    }
    response = requests.post(TEAMS_WEBHOOK_URL, json=payload)
    return response.status_code in (200, 202)
