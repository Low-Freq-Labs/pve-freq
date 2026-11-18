"""F10 server-side ownership for stored lab-tool credentials."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from freq.modules import serve


def _load_config_response(*, stored_key: str) -> dict[str, object]:
    responses: list[tuple[dict[str, object], int]] = []
    handler = serve.FreqHandler.__new__(serve.FreqHandler)
    handler.path = "/api/lab-tool/config?tool=sonarr"
    handler._json_response = lambda payload, status=200: responses.append((payload, status))

    def read_vault(_cfg, _section: str, name: str) -> str:
        if name == "sonarr_host":
            return "192.0.2.44"
        if name == "sonarr_api_key":
            return stored_key
        raise AssertionError(f"unexpected vault field: {name}")

    with (
        patch.object(serve, "_check_session_role", return_value=("operator", "")),
        patch.object(serve, "load_config", return_value=SimpleNamespace()),
        patch.object(serve, "vault_get", side_effect=read_vault),
    ):
        handler._serve_lab_tool_config()

    assert len(responses) == 1
    payload, status = responses[0]
    assert status == 200
    return payload


def test_lab_tool_config_projects_presence_without_returning_stored_secret() -> None:
    stored_key = "F10_STORED_SECRET_MUST_NEVER_REACH_THE_BROWSER"
    payload = _load_config_response(stored_key=stored_key)

    assert payload == {"host": "192.0.2.44", "key_set": True}
    assert stored_key not in json.dumps(payload, sort_keys=True)


def test_lab_tool_config_reports_missing_key_without_secret_shaped_field() -> None:
    payload = _load_config_response(stored_key="")

    assert payload == {"host": "192.0.2.44", "key_set": False}
    assert all("key" not in name or name == "key_set" for name in payload)
