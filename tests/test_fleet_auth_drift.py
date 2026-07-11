"""Hermetic integration checks for fleet authentication contracts."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from freq.modules.pve import _pve_api_call


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_service_account_exists_on_disposable_target(ephemeral_lab):
    result = ephemeral_lab.ssh(f"id {ephemeral_lab.user}")
    assert result.returncode == 0, result.stderr
    assert f"({ephemeral_lab.user})" in result.stdout


def test_service_account_has_passwordless_sudo(ephemeral_lab):
    result = ephemeral_lab.ssh("whoami", use_sudo=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "root"


def test_ephemeral_private_key_exists(ephemeral_lab):
    assert ephemeral_lab.key.is_file()
    assert ephemeral_lab.key.stat().st_size > 0


def test_ephemeral_private_key_permissions_are_600(ephemeral_lab):
    assert os.stat(ephemeral_lab.key).st_mode & 0o777 == 0o600


def test_pve_token_is_sent_to_a_hermetic_api_boundary():
    cfg = SimpleNamespace(
        pve_api_token_id="freqtest@pam!fixture",
        pve_api_token_secret="fixture-secret",
        pve_api_verify_ssl=False,
        credentials_dir="/nonexistent",
    )
    with patch(
        "freq.modules.pve.urllib.request.urlopen",
        return_value=_Response({"data": {"version": "8.2"}}),
    ) as urlopen:
        data, ok = _pve_api_call(cfg, "127.0.0.1", "/version")

    assert ok is True
    assert data == {"version": "8.2"}
    request = urlopen.call_args.args[0]
    assert request.get_header("Authorization") == (
        "PVEAPIToken=freqtest@pam!fixture=fixture-secret"
    )
