"""Release-update query and projection below dashboard scheduling."""

import json
import urllib.request


def query_latest_release(current_version, checked_at):
    """Return the latest public release or an honest unreachable result."""
    try:
        url = "https://api.github.com/repos/lowfreqlabs/pve-freq/releases/latest"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "PVE-FREQ-UpdateCheck"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode())
        latest = data.get("tag_name", "").lstrip("v")
        return {
            "current": current_version,
            "latest": latest,
            "update_available": latest and latest != current_version,
            "release_url": data.get("html_url", ""),
            "checked_at": checked_at,
        }
    except Exception:
        return {
            "current": current_version,
            "latest": "",
            "update_available": False,
            "release_url": "",
            "checked_at": checked_at,
            "error": "Could not reach GitHub",
        }
