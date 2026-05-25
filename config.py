import os
from dotenv import load_dotenv

load_dotenv()

JIRA_URL = os.getenv("JIRA_URL", "https://datacor.atlassian.net")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
JIRA_PROJECT = os.getenv("JIRA_PROJECT", "FOR")

STALE_DAYS_THRESHOLD = int(os.getenv("STALE_DAYS_THRESHOLD", "3"))

PO_TRANSITION_FROM = os.getenv("PO_TRANSITION_FROM", "PO Review")
PO_TRANSITION_TO = os.getenv("PO_TRANSITION_TO", "PO Accepted")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "")
