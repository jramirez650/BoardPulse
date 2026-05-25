import os
import requests
import msal
from config import TEAMS_WEBHOOK_URL

TENANT_ID = os.getenv("AZURE_TENANT_ID", "datacor.com")
# Microsoft Teams client ID — registered in all Microsoft 365 tenants
CLIENT_ID = "1fec8e78-bce4-4aaf-ab1b-5451cc387264"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
# Graph API scope — standard Teams messaging permission
SCOPES = ["https://graph.microsoft.com/ChannelMessage.Send",
          "https://graph.microsoft.com/Team.ReadBasic.All",
          "https://graph.microsoft.com/Channel.ReadBasic.All"]

TEAMS_TEAM_NAME    = os.getenv("TEAMS_TEAM_NAME", "")
TEAMS_CHANNEL_NAME = os.getenv("TEAMS_CHANNEL_NAME", "")

TOKEN_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".token_cache.json")


def _get_token():
    import logging
    log = logging.getLogger("boardpulse")

    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_FILE):
        cache.deserialize(open(TOKEN_CACHE_FILE, "r").read())
        log.info(f"      Token cache loaded from: {TOKEN_CACHE_FILE}")
    else:
        log.info(f"      No token cache found — will authenticate")

    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

    accounts = app.get_accounts()
    result = None
    if accounts:
        log.info(f"      Cached account: {accounts[0].get('username')} — trying silent auth...")
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result:
            log.info("      Silent auth succeeded")

    if not result:
        log.info("      Starting device code flow...")
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "error" in flow:
            raise Exception(f"Device flow error: {flow.get('error')} - {flow.get('error_description')}")
        print(f"\n   🔐 Teams auth required:\n   {flow['message']}\n")
        result = app.acquire_token_by_device_flow(flow)

    if "access_token" in result:
        with open(TOKEN_CACHE_FILE, "w") as f:
            f.write(cache.serialize())
        log.info(f"      Token saved to: {TOKEN_CACHE_FILE}")
        return result["access_token"]

    raise Exception(f"Authentication failed: {result.get('error_description', result)}")


def _get_team_and_channel(token):
    """Discover team ID and channel ID by name from Graph API."""
    import logging
    log = logging.getLogger("boardpulse")

    headers = {"Authorization": f"Bearer {token}"}

    # Get joined teams
    log.info(f"      Looking up team: '{TEAMS_TEAM_NAME}'")
    r = requests.get("https://graph.microsoft.com/v1.0/me/joinedTeams", headers=headers)
    r.raise_for_status()
    teams = r.json().get("value", [])

    team = next((t for t in teams if t["displayName"].lower() == TEAMS_TEAM_NAME.lower()), None)
    if not team:
        available = [t["displayName"] for t in teams]
        raise Exception(f"Team '{TEAMS_TEAM_NAME}' not found. Available: {available}")

    team_id = team["id"]
    log.info(f"      Team found: {team['displayName']} ({team_id})")

    # Get channels in that team
    log.info(f"      Looking up channel: '{TEAMS_CHANNEL_NAME}'")
    r = requests.get(f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels", headers=headers)
    r.raise_for_status()
    channels = r.json().get("value", [])

    channel = next((c for c in channels if c["displayName"].lower() == TEAMS_CHANNEL_NAME.lower()), None)
    if not channel:
        available = [c["displayName"] for c in channels]
        raise Exception(f"Channel '{TEAMS_CHANNEL_NAME}' not found. Available: {available}")

    channel_id = channel["id"]
    log.info(f"      Channel found: {channel['displayName']}")

    return team_id, channel_id


def send_to_teams(message):
    import logging
    log = logging.getLogger("boardpulse")

    # Allow a pre-fetched token (e.g. from Graph Explorer) to skip MSAL auth
    static_token = os.getenv("GRAPH_ACCESS_TOKEN", "")
    token = static_token if static_token else _get_token()

    team_id, channel_id = _get_team_and_channel(token)

    url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "body": {
            "contentType": "text",
            "content": message,
        }
    }

    response = requests.post(url, headers=headers, json=payload)
    log.info(f"      Graph API response: {response.status_code}")
    return response.status_code in (200, 201)
