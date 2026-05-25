import requests
from config import TEAMS_WEBHOOK_URL


def send_to_teams(message):
    payload = {"text": message}
    response = requests.post(TEAMS_WEBHOOK_URL, json=payload)
    return response.status_code == 200
