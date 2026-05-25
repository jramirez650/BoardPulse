import base64
import requests
from config import JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT


def get_auth_header():
    credentials = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
    }


def get_sprint_tickets():
    jql = f"sprint in openSprints() AND project = {JIRA_PROJECT}"
    url = f"{JIRA_URL}/rest/api/3/search"
    params = {
        "jql": jql,
        "expand": "changelog",
        "maxResults": 50,
    }
    response = requests.get(url, headers=get_auth_header(), params=params)
    response.raise_for_status()
    return response.json()["issues"]


def get_issue_changelog(issue_key):
    url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}/changelog"
    response = requests.get(url, headers=get_auth_header())
    response.raise_for_status()
    return response.json()
