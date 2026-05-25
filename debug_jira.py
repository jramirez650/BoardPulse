import json
from jira_client import get_auth_header, JIRA_URL, JIRA_PROJECT
import requests

jql = f'sprint in openSprints() AND project = "{JIRA_PROJECT}"'
url = f"{JIRA_URL}/rest/api/3/search/jql"
payload = {"jql": jql, "expand": "changelog", "maxResults": 1}
r = requests.post(url, headers=get_auth_header(), json=payload)
data = r.json()

print("Top-level keys:", list(data.keys()))
if data.get("issues"):
    issue = data["issues"][0]
    print("Issue keys:", list(issue.keys()))
    print("Sample issue:", json.dumps(issue, indent=2)[:1000])
elif data.get("values"):
    issue = data["values"][0]
    print("Values[0] keys:", list(issue.keys()))
    print("Sample:", json.dumps(issue, indent=2)[:1000])
