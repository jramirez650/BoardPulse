import os
import requests
import msal
from config import TEAMS_WEBHOOK_URL

TENANT_ID = os.getenv("AZURE_TENANT_ID", "datacor.com")
# Well-known public client ID (Azure CLI) — works in most enterprise tenants
CLIENT_ID = "04b07795-8542-4562-827a-cdbbec8f3d12"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://api.powerplatform.com/.default"]
TOKEN_CACHE_FILE = ".token_cache.json"


def _get_token():
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_FILE):
        cache.deserialize(open(TOKEN_CACHE_FILE, "r").read())

    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

    # Try silent auth first (uses cached token)
    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    # If no cached token, launch device code flow (opens browser once)
    if not result:
        flow = app.initiate_device_flow(scopes=SCOPES)
        print(f"\n   🔐 Teams auth required:\n   {flow['message']}\n")
        result = app.acquire_token_by_device_flow(flow)

    if "access_token" in result:
        # Save token to cache for next run
        with open(TOKEN_CACHE_FILE, "w") as f:
            f.write(cache.serialize())
        return result["access_token"]

    raise Exception(f"Authentication failed: {result.get('error_description', result)}")


def send_to_teams(message):
    token = _get_token()
    payload = {"text": message}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = requests.post(TEAMS_WEBHOOK_URL, headers=headers, json=payload)
    print(f"   Teams response: {response.status_code}")
    return response.status_code in (200, 202)
