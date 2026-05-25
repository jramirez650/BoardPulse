import os
import requests
import msal
from config import TEAMS_WEBHOOK_URL

TENANT_ID = os.getenv("AZURE_TENANT_ID", "datacor.com")
# Power Automate first-party client ID — pre-registered in all Microsoft 365 tenants
CLIENT_ID = "57fcbcfa-7cee-4eb1-8b25-12d2030b4ee0"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://api.powerplatform.com/.default"]
# Use absolute path so the cache is always found regardless of working directory
TOKEN_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".token_cache.json")


def _get_token():
    import logging
    log = logging.getLogger("boardpulse")

    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_FILE):
        cache.deserialize(open(TOKEN_CACHE_FILE, "r").read())
        log.info(f"      Token cache loaded from: {TOKEN_CACHE_FILE}")
    else:
        log.info(f"      No token cache found at: {TOKEN_CACHE_FILE} — will authenticate")

    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

    # Try silent auth first (uses cached token)
    accounts = app.get_accounts()
    result = None
    if accounts:
        log.info(f"      Found cached account: {accounts[0].get('username')} — trying silent auth...")
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result:
            log.info("      Silent auth succeeded — no browser needed")

    # If no cached token, launch device code flow (opens browser once)
    if not result:
        log.info("      No valid cached token — starting device code flow...")
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "error" in flow:
            raise Exception(f"Device flow init failed: {flow.get('error')} - {flow.get('error_description')}")
        print(f"\n   🔐 Teams auth required:\n   {flow['message']}\n")
        result = app.acquire_token_by_device_flow(flow)

    if "access_token" in result:
        # Save token to cache for next run
        with open(TOKEN_CACHE_FILE, "w") as f:
            f.write(cache.serialize())
        log.info(f"      Token saved to cache: {TOKEN_CACHE_FILE}")
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
