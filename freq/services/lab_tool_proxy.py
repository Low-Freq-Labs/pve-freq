"""Allow-listed lab-tool requests below dashboard HTTP transport."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

LAB_TOOL_REGISTRY = {
    "gwipe": {
        "default_port": 7980,
        "api_base": "/api/v1",
        "auth_header": "X-API-Key",
        "endpoints": frozenset(
            {
                "status",
                "drives",
                "drives/list",
                "jobs",
                "jobs/list",
            }
        ),
    },
}


def lab_tool_request(tool_id: str, host: str, key: str, endpoint: str) -> dict:
    """Execute one allow-listed GET and return its transport-neutral outcome."""
    tool = LAB_TOOL_REGISTRY.get(tool_id)
    if not tool:
        return {"error": f"Unknown lab tool: {tool_id}"}
    if endpoint not in tool["endpoints"]:
        return {"error": f"Endpoint {endpoint!r} not allowed for {tool_id}"}
    port = tool["default_port"]
    base = tool["api_base"].rstrip("/")
    url = f"http://{host}:{port}{base}/{endpoint}"
    request = urllib.request.Request(url, method="GET")
    request.add_header(tool["auth_header"], key)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        try:
            error_body = json.loads(error.read().decode())
            return {"error": error_body.get("error", f"HTTP {error.code}")}
        except (json.JSONDecodeError, ValueError):
            return {"error": f"HTTP {error.code}"}
    except urllib.error.URLError as error:
        return {"error": f"Cannot reach {tool_id} at {host}:{port} — {error.reason}"}
    except Exception as error:
        return {"error": str(error)}
