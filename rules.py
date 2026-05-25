from datetime import datetime, timezone
from config import STALE_DAYS_THRESHOLD, PO_TRANSITION_FROM, PO_TRANSITION_TO


def detect_stale_tickets(issues):
    stale = []
    now = datetime.now(timezone.utc)

    for issue in issues:
        key = issue["key"]
        summary = issue["fields"]["summary"]
        status = issue["fields"]["status"]["name"]
        assignee = issue["fields"].get("assignee") or {}
        assignee_name = assignee.get("displayName", "Sin asignar")

        updated_raw = issue["fields"]["updated"].replace("+0000", "+00:00")
        updated = datetime.fromisoformat(updated_raw)
        days_since_update = (now - updated).days

        if days_since_update >= STALE_DAYS_THRESHOLD:
            stale.append({
                "key": key,
                "summary": summary,
                "status": status,
                "assignee": assignee_name,
                "days_stale": days_since_update,
            })

    return stale


def detect_po_accepted(issues):
    recently_accepted = []

    for issue in issues:
        key = issue["key"]
        summary = issue["fields"]["summary"]
        assignee = issue["fields"].get("assignee") or {}
        assignee_name = assignee.get("displayName", "Sin asignar")

        changelog = issue.get("changelog", {}).get("histories", [])

        for history in changelog:
            for item in history.get("items", []):
                if (
                    item.get("field") == "status"
                    and item.get("fromString") == PO_TRANSITION_FROM
                    and item.get("toString") == PO_TRANSITION_TO
                ):
                    recently_accepted.append({
                        "key": key,
                        "summary": summary,
                        "assignee": assignee_name,
                        "transition_date": history["created"],
                    })

    return recently_accepted
