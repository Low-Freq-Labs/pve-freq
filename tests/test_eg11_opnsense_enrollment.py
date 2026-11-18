"""EG11 owners for first-class, fail-closed OPNsense enrollment."""

import hashlib
import base64
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class _Response:
    def __init__(self, body: bytes, server: str = ""):
        self._body = body
        self.headers = {"Server": server}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return self._body


class _HTTPResponse:
    def __init__(self, status, body=b"", headers=None):
        self.status = status
        self._body = body
        self._headers = list(headers or [])

    def read(self, _limit=-1):
        return self._body

    def getheaders(self):
        return list(self._headers)

    def getheader(self, name, default=None):
        for key, value in self._headers:
            if key.lower() == name.lower():
                return value
        return default


class _HTTPConnection:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.sock = SimpleNamespace(getpeercert=lambda **_kwargs: b"leaf")

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, dict(headers or {})))

    def getresponse(self):
        return self.responses.pop(0)

    def close(self):
        self.sock = None


class TestOPNsenseIdentity(unittest.TestCase):
    def test_opnsense_is_an_exact_firewall_vendor(self):
        from freq.deployers import get_deployer, resolve_htype

        self.assertEqual(resolve_htype("opnsense"), ("firewall", "opnsense"))
        deployer = get_deployer("firewall", "opnsense")
        self.assertIsNotNone(deployer)
        self.assertFalse(getattr(deployer, "STUB", True))

    def test_discovery_does_not_collapse_opnsense_to_pfsense(self):
        from freq.core import setup_discovery

        opener = Mock()
        opener.open.return_value = _Response(b"<title>OPNsense</title>")
        with patch("freq.core.setup_discovery.urllib.request.build_opener", return_value=opener):
            self.assertEqual(setup_discovery._http_fingerprint("172.20.0.1"), ("opnsense", "https"))
        self.assertEqual(
            setup_discovery._device_credential_fields("opnsense"),
            ["bootstrap_mode", "username", "password", "api_key", "api_secret", "tls_sha256", "trust_on_first_use"],
        )


class TestOPNsenseBootstrapContract(unittest.TestCase):
    def _discovery(self):
        return {
            "id": "discovery-eg11",
            "results": {
                "resources": [],
                "devices": [
                    {
                        "id": "device:opnsense:172.20.0.1",
                        "kind": "opnsense",
                        "label": "edge",
                        "host": "172.20.0.1",
                    }
                ],
            },
        }

    def _body(self):
        return {
            "schema": "zero-state-web-v1",
            "setup_id": "setup-eg11",
            "discovery_id": "discovery-eg11",
            "selections": [
                {
                    "resource_id": "device:opnsense:172.20.0.1",
                    "disposition": "owned",
                    "placement": "lab",
                }
            ],
        }

    def test_setup_contract_exposes_exact_modes_without_ssh(self):
        from freq.core.setup_contract import build_setup_contract

        contract = build_setup_contract(
            self._body(), self._discovery(), setup_id="setup-eg11", now=1
        )
        requirement = contract["credential_requirements"][0]
        self.assertEqual(
            requirement["bootstrap_modes"],
            {
                "web": ["username", "password"],
                "api": ["api_key", "api_secret"],
            },
        )
        self.assertEqual(
            set(requirement["allowed_fields"]),
            {
                "bootstrap_mode",
                "username",
                "password",
                "api_key",
                "api_secret",
                "tls_sha256",
                "trust_on_first_use",
            },
        )
        self.assertNotIn("ssh_private_key", requirement["allowed_fields"])

    def test_web_and_api_bootstrap_are_mode_specific(self):
        from freq.core.opnsense_enrollment import validate_bootstrap

        pin = "ab" * 32
        web = validate_bootstrap(
            {
                "bootstrap_mode": "web",
                "username": "root",
                "password": "secret",
                "tls_sha256": pin,
            }
        )
        self.assertEqual(web["tls_sha256"], pin)
        self.assertEqual(set(web), {"bootstrap_mode", "username", "password", "tls_sha256"})

        api = validate_bootstrap(
            {
                "bootstrap_mode": "api",
                "api_key": "key",
                "api_secret": "secret",
                "trust_on_first_use": True,
            }
        )
        self.assertTrue(api["trust_on_first_use"])
        self.assertEqual(set(api), {"bootstrap_mode", "api_key", "api_secret", "trust_on_first_use"})

    def test_partial_or_cross_mode_credentials_fail_with_field_focus(self):
        from freq.core.opnsense_enrollment import OPNsenseContractError, validate_bootstrap

        bad_rows = (
            ({"bootstrap_mode": "api", "api_key": "key", "trust_on_first_use": True}, "api_secret"),
            (
                {
                    "bootstrap_mode": "web",
                    "username": "root",
                    "password": "secret",
                    "api_key": "cross-mode",
                    "trust_on_first_use": True,
                },
                "api_key",
            ),
            (
                {
                    "bootstrap_mode": "web",
                    "username": "root",
                    "password": "secret",
                    "ssh_private_key": "forbidden",
                    "trust_on_first_use": True,
                },
                "ssh_private_key",
            ),
        )
        for body, field in bad_rows:
            with self.subTest(field=field), self.assertRaises(OPNsenseContractError) as caught:
                validate_bootstrap(body)
            self.assertEqual(caught.exception.field, field)

    def test_zero_state_credential_request_preserves_api_secret_and_mode(self):
        from freq.core.setup_contract import (
            build_setup_contract,
            credential_presence,
            credential_storage_value,
            credential_vault_key,
            validate_credential_request,
        )

        contract = build_setup_contract(
            self._body(), self._discovery(), setup_id="setup-eg11", now=1
        )
        normalized = validate_credential_request(
            {
                "schema": "zero-state-web-v1",
                "setup_id": "setup-eg11",
                "contract_id": contract["contract_id"],
                "credentials": [
                    {
                        "resource_id": "device:opnsense:172.20.0.1",
                        "bootstrap_mode": "api",
                        "trust_on_first_use": True,
                        "secrets": {"api_key": "key", "api_secret": "secret"},
                    }
                ],
            },
            contract,
            "setup-eg11",
        )
        values = normalized["credentials"][0]["values"]
        self.assertEqual(values["bootstrap_mode"], "api")
        self.assertEqual(values["api_secret"], "secret")
        self.assertEqual(credential_storage_value("trust_on_first_use", True), "true")
        self.assertEqual(
            set(normalized["credentials"][0]["clear_fields"]),
            {"username", "password", "tls_sha256"},
        )

        stored = {
            credential_vault_key("device:opnsense:172.20.0.1", field): value
            for field, value in values.items()
        }
        rows = credential_presence(contract, lambda key: stored.get(key, ""))
        self.assertTrue(rows[0]["complete"])
        self.assertEqual(rows[0]["bootstrap_mode"], "api")
        self.assertTrue(rows[0]["trust_on_first_use"])


class TestOPNsenseTLSAndPublicTruth(unittest.TestCase):
    def test_runtime_pin_is_checked_before_vault_secrets_are_read(self):
        from freq.api import opnsense

        cfg = SimpleNamespace(opnsense_ip="172.20.0.1", opnsense_tls_sha256="aa" * 32)
        with (
            patch.object(opnsense, "_observed_tls_sha256", return_value="bb" * 32),
            patch.object(opnsense, "vault_get") as vault_get,
        ):
            data, failure = opnsense._opn_request(cfg, "core/system/status")
        self.assertIsNone(data)
        self.assertEqual(failure["code"], "opnsense_tls_pin_mismatch")
        self.assertEqual(failure["field"], "tls_sha256")
        vault_get.assert_not_called()

    def test_public_failures_are_closed_and_secret_free(self):
        from freq.core.opnsense_enrollment import public_failure

        expected = {
            "tls_untrusted": (409, "opnsense_tls_untrusted", "tls_sha256"),
            "pin_mismatch": (409, "opnsense_tls_pin_mismatch", "tls_sha256"),
            "auth": (401, "opnsense_auth_failed", "credentials"),
            "rollback": (502, "opnsense_enrollment_rollback_failed", ""),
            "cleanup_partial": (502, "opnsense_cleanup_partial", ""),
        }
        for kind, (status, code, field) in expected.items():
            with self.subTest(kind=kind):
                actual_status, payload = public_failure(kind)
                self.assertEqual(actual_status, status)
                self.assertEqual(payload["code"], code)
                self.assertEqual(payload["field"], field)
                self.assertEqual(payload["details"], [])
                rendered = repr(payload).lower()
                self.assertNotIn("password", rendered)
                self.assertNotIn("api_secret", rendered)

    def test_non_secret_state_payload_is_bounded(self):
        from freq.core.opnsense_enrollment import managed_state_payload

        payload = managed_state_payload(
            managed=True,
            tls_sha256="cd" * 32,
            managed_user_count=1,
            managed_key_count=1,
            remote_present=True,
            local_present=True,
            ignored_secret="must-not-leak",
        )
        self.assertEqual(
            set(payload),
            {
                "managed",
                "tls_sha256",
                "managed_user_count",
                "managed_key_count",
                "remote_present",
                "local_present",
            },
        )
        self.assertNotIn("must-not-leak", repr(payload))

    def test_config_has_non_secret_opnsense_pin(self):
        from freq.core.config import FreqConfig

        cfg = FreqConfig()
        self.assertEqual(cfg.opnsense_tls_sha256, "")

    def test_certificate_digest_is_sha256_hex(self):
        from freq.core.opnsense_enrollment import certificate_sha256

        certificate = b"leaf-certificate-der"
        self.assertEqual(certificate_sha256(certificate), hashlib.sha256(certificate).hexdigest())


class TestOPNsensePostSetupReachability(unittest.TestCase):
    def test_post_init_routes_are_registered(self):
        from freq.api.opnsense import register

        routes = {}
        register(routes)
        self.assertIn("/api/opnsense/enrollment", routes)
        self.assertIn("/api/opnsense/retrust", routes)
        self.assertIn("/api/opnsense/remove", routes)

    def test_retrust_exposes_bound_and_observed_before_credentials_cross(self):
        from freq.api import opnsense

        handler = SimpleNamespace(command="POST")
        handler._captured = None
        handler._status = None

        def respond(_handler, payload, status=200):
            handler._captured = payload
            handler._status = status
        body = {
            "host": "172.20.0.1",
            "bootstrap_mode": "api",
            "api_key": "bootstrap-key",
            "api_secret": "bootstrap-secret",
            "tls_sha256": "bb" * 32,
        }
        cfg = SimpleNamespace(
            opnsense_ip="172.20.0.1",
            opnsense_tls_sha256="aa" * 32,
            ssh_service_account="freq-admin",
        )
        with (
            patch.object(opnsense, "require_post", return_value=False),
            patch.object(opnsense, "_check_session_role", return_value=("admin", "")),
            patch.object(opnsense, "load_config", return_value=cfg),
            patch.object(opnsense, "get_json_body", return_value=body),
            patch.object(opnsense, "_observed_tls_sha256", return_value="bb" * 32),
            patch.object(opnsense, "_BootstrapSession") as session,
            patch.object(opnsense, "json_response", side_effect=respond),
        ):
            opnsense.handle_opnsense_retrust(handler)
        self.assertEqual(handler._status, 409)
        self.assertEqual(handler._captured["code"], "opnsense_retrust_failed")
        self.assertEqual(
            handler._captured["details"],
            [{"bound": "aa" * 32, "observed": "bb" * 32}],
        )
        session.assert_not_called()

    def test_remove_rejects_a_host_other_than_the_bound_device_before_tls_or_auth(self):
        from freq.api import opnsense

        handler = SimpleNamespace(command="POST", _captured=None, _status=None)

        def respond(_handler, payload, status=200):
            handler._captured = payload
            handler._status = status

        cfg = SimpleNamespace(
            opnsense_ip="172.20.0.1",
            opnsense_tls_sha256="aa" * 32,
            ssh_service_account="freq-admin",
        )
        body = {
            "host": "172.20.0.2",
            "bootstrap_mode": "api",
            "api_key": "bootstrap-key",
            "api_secret": "bootstrap-secret",
            "tls_sha256": "aa" * 32,
        }
        with (
            patch.object(opnsense, "require_post", return_value=False),
            patch.object(opnsense, "_check_session_role", return_value=("admin", "")),
            patch.object(opnsense, "load_config", return_value=cfg),
            patch.object(opnsense, "get_json_body", return_value=body),
            patch.object(opnsense, "_observed_tls_sha256") as observe,
            patch.object(opnsense, "_BootstrapSession") as session,
            patch.object(opnsense, "json_response", side_effect=respond),
        ):
            opnsense.handle_opnsense_remove(handler)
        self.assertEqual(handler._status, 409)
        self.assertEqual(handler._captured["code"], "opnsense_remove_target_mismatch")
        self.assertEqual(handler._captured["field"], "host")
        observe.assert_not_called()
        session.assert_not_called()

    def test_remove_rejects_a_changed_certificate_before_credentials_cross(self):
        from freq.api import opnsense

        handler = SimpleNamespace(command="POST", _captured=None, _status=None)

        def respond(_handler, payload, status=200):
            handler._captured = payload
            handler._status = status

        cfg = SimpleNamespace(
            opnsense_ip="172.20.0.1",
            opnsense_tls_sha256="aa" * 32,
            ssh_service_account="freq-admin",
        )
        body = {
            "host": "172.20.0.1",
            "bootstrap_mode": "api",
            "api_key": "bootstrap-key",
            "api_secret": "bootstrap-secret",
            "trust_on_first_use": True,
        }
        with (
            patch.object(opnsense, "require_post", return_value=False),
            patch.object(opnsense, "_check_session_role", return_value=("admin", "")),
            patch.object(opnsense, "load_config", return_value=cfg),
            patch.object(opnsense, "get_json_body", return_value=body),
            patch.object(opnsense, "_observed_tls_sha256", return_value="bb" * 32),
            patch.object(opnsense, "_BootstrapSession") as session,
            patch.object(opnsense, "json_response", side_effect=respond),
        ):
            opnsense.handle_opnsense_remove(handler)
        self.assertEqual(handler._status, 409)
        self.assertEqual(handler._captured["code"], "opnsense_retrust_failed")
        self.assertEqual(
            handler._captured["details"],
            [{"bound": "aa" * 32, "observed": "bb" * 32}],
        )
        session.assert_not_called()

    def test_state_is_managed_only_with_exactly_one_remote_key(self):
        from freq.api import opnsense

        cfg = SimpleNamespace(
            opnsense_ip="172.20.0.1",
            opnsense_tls_sha256="aa" * 32,
            ssh_service_account="freq-admin",
        )
        opened = Mock()
        opened.managed_user_present.return_value = True
        opened.managed_keys.return_value = [{"id": "one"}, {"id": "two"}]
        session = Mock()
        session.open.return_value = opened
        with (
            patch.object(opnsense, "_local_pair", return_value={"api_key": "key", "api_secret": "secret"}),
            patch.object(opnsense, "_BootstrapSession", return_value=session),
        ):
            state = opnsense._current_managed_state(cfg)
        self.assertFalse(state["managed"])
        self.assertEqual(state["managed_key_count"], 2)


class TestOPNsenseUpstreamAuthContract(unittest.TestCase):
    def _session(self):
        from freq.api.opnsense import _BootstrapSession

        return _BootstrapSession(
            "172.20.0.1",
            "aa" * 32,
            {
                "bootstrap_mode": "api",
                "api_key": "bootstrap-key",
                "api_secret": "bootstrap-secret",
                "tls_sha256": "aa" * 32,
            },
        )

    def test_key_inventory_uses_the_upstream_get_contract(self):
        session = self._session()
        session._api = Mock(
            return_value={"rows": [{"username": "freq-admin", "key": "key", "id": "encoded"}]}
        )
        self.assertEqual(session.managed_keys("freq-admin"), [{"id": "encoded"}])
        session._api.assert_called_once_with(
            "auth/user/search_api_key", method="GET"
        )

    def test_generated_key_id_is_the_upstream_base64_key_identifier(self):
        session = self._session()
        session._api = Mock(return_value={"result": "ok", "key": "new-key", "secret": "new-secret"})
        generated = session.add_managed_key("freq-admin")
        self.assertEqual(
            generated,
            {
                "id": base64.b64encode(b"new-key").decode("ascii"),
                "key": "new-key",
                "secret": "new-secret",
            },
        )

    def test_web_bootstrap_loads_rendered_csrf_before_api_post(self):
        from freq.api import opnsense

        session = opnsense._BootstrapSession(
            "172.20.0.1",
            "aa" * 32,
            {
                "bootstrap_mode": "web",
                "username": "root",
                "password": "bootstrap-secret",
                "tls_sha256": "aa" * 32,
            },
        )
        connection = _HTTPConnection(
            [
                _HTTPResponse(200, b'<input name="usernamefld">', [("Set-Cookie", "PHPSESSID=old; Secure")]),
                _HTTPResponse(302, b"", [("Set-Cookie", "PHPSESSID=new; Secure")]),
                _HTTPResponse(
                    200,
                    b'xhr.setRequestHeader("X-CSRFToken", "csrf-value" );',
                    [("Content-Type", "text/html")],
                ),
                _HTTPResponse(200, b'{"rows": []}', [("Content-Type", "application/json")]),
            ]
        )
        with (
            patch.object(session, "_connect", return_value=connection),
            patch.object(opnsense, "certificate_sha256", return_value="aa" * 32),
        ):
            session.open()
            session._api("auth/user/search", method="POST", body={})
        self.assertEqual(connection.requests[2][0:2], ("GET", "/ui/core/dashboard"))
        self.assertEqual(connection.requests[3][3]["X-CSRFToken"], "csrf-value")


class _LifecycleSession:
    def __init__(self, *, user_present=False, keys=None, valid_pairs=None, rollback_ok=True):
        self.user_present = user_present
        self.keys = list(keys or [])
        self.valid_pairs = set(valid_pairs or set())
        self.rollback_ok = rollback_ok
        self.calls = []

    def verify_credentials(self, key, secret):
        self.calls.append(("verify", key, secret))
        return (key, secret) in self.valid_pairs

    def managed_user_present(self, username):
        self.calls.append(("user_present", username))
        return self.user_present

    def add_managed_user(self, username):
        self.calls.append(("add_user", username))
        self.user_present = True

    def managed_keys(self, username):
        self.calls.append(("keys", username))
        return list(self.keys)

    def delete_managed_key(self, key_id):
        self.calls.append(("delete_key", key_id))
        if self.rollback_ok:
            self.keys = [row for row in self.keys if row["id"] != key_id]

    def add_managed_key(self, username):
        self.calls.append(("add_key", username))
        row = {"id": "new-id", "key": "new-key", "secret": "new-secret"}
        self.keys.append({"id": row["id"]})
        self.valid_pairs.add((row["key"], row["secret"]))
        return row

    def delete_managed_user(self, username):
        self.calls.append(("delete_user", username))
        if self.rollback_ok:
            self.user_present = False
            self.keys = []


class TestOPNsenseLifecycle(unittest.TestCase):
    def test_valid_rerun_reuses_managed_pair_without_new_key(self):
        from freq.core.opnsense_lifecycle import enroll_managed_identity

        session = _LifecycleSession(
            user_present=True,
            keys=[{"id": "existing-id"}],
            valid_pairs={("existing-key", "existing-secret")},
        )
        stored = []
        state = enroll_managed_identity(
            session,
            "freq-admin",
            "ab" * 32,
            load_local=lambda: {"api_key": "existing-key", "api_secret": "existing-secret"},
            store_local=lambda *_args: stored.append(_args) or True,
        )
        self.assertEqual(state["managed_key_count"], 1)
        self.assertNotIn("add_key", [call[0] for call in session.calls])
        self.assertEqual(stored, [])

    def test_new_enrollment_replaces_stale_keys_and_persists_after_probe(self):
        from freq.core.opnsense_lifecycle import enroll_managed_identity

        session = _LifecycleSession(user_present=True, keys=[{"id": "stale-id"}])
        stored = []
        state = enroll_managed_identity(
            session,
            "freq-admin",
            "ab" * 32,
            load_local=lambda: {},
            store_local=lambda key, secret, pin: stored.append((key, secret, pin)) or True,
        )
        self.assertEqual(stored, [("new-key", "new-secret", "ab" * 32)])
        self.assertEqual(state["managed_user_count"], 1)
        self.assertEqual(state["managed_key_count"], 1)
        self.assertLess(
            session.calls.index(("verify", "new-key", "new-secret")),
            len(session.calls),
        )

    def test_valid_pair_with_extra_key_is_rotated_to_one(self):
        from freq.core.opnsense_lifecycle import enroll_managed_identity

        session = _LifecycleSession(
            user_present=True,
            keys=[{"id": "current"}, {"id": "extra"}],
            valid_pairs={("current-key", "current-secret")},
        )
        state = enroll_managed_identity(
            session,
            "freq-admin",
            "ab" * 32,
            load_local=lambda: {"api_key": "current-key", "api_secret": "current-secret"},
            store_local=lambda *_args: True,
        )
        self.assertEqual(state["managed_key_count"], 1)
        self.assertEqual(session.keys, [{"id": "new-id"}])

    def test_persistence_failure_rolls_back_remote_identity(self):
        from freq.core.opnsense_lifecycle import OPNsenseLifecycleError, enroll_managed_identity

        session = _LifecycleSession()
        with self.assertRaises(OPNsenseLifecycleError) as caught:
            enroll_managed_identity(
                session,
                "freq-admin",
                "ab" * 32,
                load_local=lambda: {},
                store_local=lambda *_args: False,
            )
        self.assertEqual(caught.exception.kind, "enrollment")
        self.assertFalse(session.user_present)
        self.assertEqual(session.keys, [])

    def test_cleanup_clears_local_only_after_remote_absence(self):
        from freq.core.opnsense_lifecycle import remove_managed_identity

        session = _LifecycleSession(user_present=True, keys=[{"id": "one"}, {"id": "two"}])
        cleared = []
        state = remove_managed_identity(
            session,
            "freq-admin",
            "ab" * 32,
            clear_local=lambda: cleared.append(True) or True,
        )
        self.assertEqual(cleared, [True])
        self.assertFalse(state["remote_present"])
        self.assertFalse(state["local_present"])

    def test_bootstrap_credentials_are_not_staged_as_runtime_device_credentials(self):
        from freq.modules import init_cmd

        with tempfile.TemporaryDirectory() as temp_dir:
            cfg = SimpleNamespace(credentials_dir=temp_dir, ssh_key_path="")
            bootstrap = {
                "opnsense-edge": {
                    "type": "opnsense",
                    "host": "172.20.0.1",
                    "bootstrap_mode": "web",
                    "user": "root",
                    "password": "must-be-ephemeral",
                    "tls_sha256": "aa" * 32,
                }
            }
            with patch.object(init_cmd, "_chown"):
                init_cmd._persist_runtime_device_credentials_metadata(
                    cfg, bootstrap, "freq-admin"
                )
            written = []
            for root, _dirs, files in os.walk(temp_dir):
                written.extend(os.path.join(root, name) for name in files)
            self.assertEqual(written, [])


if __name__ == "__main__":
    unittest.main()
