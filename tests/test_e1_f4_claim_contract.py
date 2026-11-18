"""Failing-first owners for E1 F4 first-admin claim authentication.

Composed design authority (Jarvis stage-1 accepted 2026-08-12):

* combined R1 SHA-256 0613918f85e81223b24b40405925461e74919c6ce03edae91b64986bace930d4
* combined R2 SHA-256 be21c3b96cc006f257b4ff157f738f577e031081d8c0178467a5d2cfcedb299d
* consumer R3 SHA-256 a02410507ee215b10582d682cdb1c04c722c7ec6a53404df47426993ace9c063
* consumed-focus amendment SHA-256 6a1c52e2fe9be80e356d0ec6c8b7d34c2975b47f5c95d52141baa5bfb46dfca7
* complete guidance-table amendment SHA-256 8a811f69a4a058ac0fbdf23e519620e3c7f680d1d3b095099b7d4c9d0994ff10
* layer-aware envelope amendment SHA-256 ef12b73c3c1404ffee88c3e80ca6460195925f12466c755cbb3b28333520ec94
* recovery lifecycle acceptance R2 SHA-256 5aaebb13ede34b38f9d4993cfab729405cca8355f63ee1be6ca09074997ff1b2

R2 supersedes R1 section 3.3 for configured-startup, recovery, and delivery
guidance; section 4 for global-bucket order/effect; section 5 steps 8-11 for
consumed/stronger-truth ordering; section 6 for setup help/public recovery
truth; and the corresponding section 7/8 proof obligations where R2 is more
specific. All other R1 and consumer R3 requirements remain normative.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import io
import json
import os
import re
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from freq.api.auth import same_origin_or_absent
from freq.core.setup_state import SCHEMA
from freq.modules import serve
from freq.modules.serve import FreqHandler

REPO_ROOT = Path(__file__).resolve().parents[1]
JSON_BODY_ROUTES = {
    "/api/auth/login",
    "/api/auth/change-password",
    "/api/ui/event",
    "/api/media/tags",
    "/api/setup/create-admin",
    "/api/setup/configure",
    "/api/setup/discovery/start",
    "/api/setup/contract",
    "/api/setup/device-credentials",
    "/api/setup/init/start",
    "/api/setup/init/cancel",
    "/api/lab-tool/save-config",
}


def _cfg(root: str) -> SimpleNamespace:
    return SimpleNamespace(
        install_dir="/opt/pve-freq",
        data_dir=os.path.join(root, "data"),
        conf_dir=os.path.join(root, "conf"),
        vault_dir=os.path.join(root, "data", "vault"),
        vault_file=os.path.join(root, "data", "vault", "vault.enc"),
        trusted_proxy_cidrs=[],
    )


def _claim_module():
    try:
        return importlib.import_module("freq.core.first_admin_claim")
    except ModuleNotFoundError:
        pytest.fail("structural red: freq.core.first_admin_claim is absent")


def _prepare_claim(claim, cfg, deliveries, *, now=1000.0, **overrides):
    def deliver(claim_id, secret, generated_at):
        deliveries.append((claim_id, secret, generated_at))

    options = {
        "users_present": False,
        "setup_complete": False,
        "deliver": deliver,
        "warn": lambda _message: None,
        "now": now,
    }
    options.update(overrides)
    return claim.prepare_first_admin_claim(cfg, **options)


def _capturing_handler(body: dict, *, headers: dict | None = None) -> FreqHandler:
    encoded = json.dumps(body).encode()
    handler = FreqHandler.__new__(FreqHandler)
    handler.path = "/api/setup/create-admin"
    handler.command = "POST"
    handler.client_address = ("192.0.2.44", 40444)
    handler.headers = {
        "Host": "freq.test",
        "Content-Type": "application/json",
        "Content-Length": str(len(encoded)),
        **(headers or {}),
    }
    handler.rfile = io.BytesIO(encoded)
    handler._captured = None
    handler._status_code = None

    def respond(payload, status=200):
        handler._captured = payload
        handler._status_code = status

    handler._json_response = respond
    return handler


def _claim_body(secret: str) -> dict:
    return {
        "schema": SCHEMA,
        "username": "operator",
        "password": "password-123",
        "claim_secret": secret,
        "client_request_id": "12345678-1234-4123-8123-123456789abc",
    }


def _seeded_claim(root: str):
    claim = _claim_module()
    cfg = _cfg(root)
    deliveries = []
    metadata = _prepare_claim(claim, cfg, deliveries)
    assert len(deliveries) == 1
    return claim, cfg, metadata, deliveries[0][1]


def test_f4_design_authority_is_composed_and_numbered():
    """Positive control: the owner itself names every immutable design input."""
    source = Path(__file__).read_text(encoding="utf-8")
    for digest in (
        "0613918f85e81223b24b40405925461e74919c6ce03edae91b64986bace930d4",
        "be21c3b96cc006f257b4ff157f738f577e031081d8c0178467a5d2cfcedb299d",
        "a02410507ee215b10582d682cdb1c04c722c7ec6a53404df47426993ace9c063",
        "6a1c52e2fe9be80e356d0ec6c8b7d34c2975b47f5c95d52141baa5bfb46dfca7",
        "8a811f69a4a058ac0fbdf23e519620e3c7f680d1d3b095099b7d4c9d0994ff10",
        "ef12b73c3c1404ffee88c3e80ca6460195925f12466c755cbb3b28333520ec94",
        "5aaebb13ede34b38f9d4993cfab729405cca8355f63ee1be6ca09074997ff1b2",
    ):
        assert digest in source
    for section in ("section 3.3", "section 4", "section 5", "section 6", "section 7/8"):
        assert section in source


def test_claim_generation_delivers_256_bits_and_persists_digest_only():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        deliveries = []
        metadata = _prepare_claim(claim, cfg, deliveries)
        assert metadata == {
            "state": "available",
            "claim_id": deliveries[0][0],
            "generated": True,
            "delivered": True,
        }
        claim_id, secret, generated_at = deliveries[0]
        assert generated_at == 1000.0
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", secret)
        assert len(secret) == 43
        state_path = Path(claim.claim_state_path(cfg))
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["schema"] == "pve-freq-first-admin-claim-v1"
        assert state["state"] == "available"
        assert state["claim_id"] == claim_id
        assert re.fullmatch(r"[0-9a-f]{64}", state["digest"])
        assert secret not in state_path.read_text(encoding="utf-8")
        assert state_path.stat().st_mode & 0o777 == 0o600
        assert state_path.parent.stat().st_mode & 0o777 == 0o700


def test_available_restart_reuses_state_without_redisplaying_secret():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        first = []
        initial = _prepare_claim(claim, cfg, first)
        second = []
        restarted = _prepare_claim(claim, cfg, second, now=1001.0)
        assert second == []
        assert restarted == {
            "state": "available",
            "claim_id": initial["claim_id"],
            "generated": False,
            "delivered": False,
        }


def test_pending_delivery_restart_replaces_old_secret_and_only_newest_matches():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        old_delivery = []

        def interrupted(claim_id, secret, generated_at):
            old_delivery.append((claim_id, secret, generated_at))
            raise OSError("delivery interrupted before available transition")

        with pytest.raises(claim.ClaimStateError, match="delivery"):
            _prepare_claim(claim, cfg, [], deliver=interrupted)
        new_delivery = []
        metadata = _prepare_claim(claim, cfg, new_delivery, now=1001.0)
        assert len(old_delivery) == len(new_delivery) == 1
        assert old_delivery[0][0] != new_delivery[0][0]
        assert old_delivery[0][1] != new_delivery[0][1]
        assert metadata["claim_id"] == new_delivery[0][0]
        with claim.locked_first_admin_claim(cfg) as transaction:
            assert transaction.matches(old_delivery[0][1]) is False
            assert transaction.matches(new_delivery[0][1]) is True


def test_zero_state_corrupt_claim_state_aborts_before_exposure():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        path = Path(claim.claim_state_path(cfg))
        path.parent.mkdir(parents=True, mode=0o700)
        path.write_text("not-json\n", encoding="utf-8")
        with pytest.raises(claim.ClaimStateError, match="unavailable"):
            _prepare_claim(claim, cfg, [])


def test_configured_corrupt_claim_state_warns_and_continues():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        path = Path(claim.claim_state_path(cfg))
        path.parent.mkdir(parents=True, mode=0o700)
        path.write_text("not-json\n", encoding="utf-8")
        warnings = []
        result = _prepare_claim(
            claim,
            cfg,
            [],
            users_present=True,
            warn=warnings.append,
        )
        assert result["state"] == "configured"
        assert result["generated"] is False
        assert warnings and all("secret" not in warning.lower() for warning in warnings)


def test_exact_candidate_bytes_use_constant_time_comparison():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        deliveries = []
        _prepare_claim(claim, cfg, deliveries)
        secret = deliveries[0][1]
        stored_digest = json.loads(
            Path(claim.claim_state_path(cfg)).read_text(encoding="utf-8")
        )["digest"]

        def candidate_digest(candidate):
            return hashlib.sha256(
                b"pve-freq-first-admin-claim-v1\0" + candidate.encode("utf-8")
            ).hexdigest()

        compared_candidates = (secret, secret + " ", secret.lower())
        with patch.object(
            claim.hmac,
            "compare_digest",
            wraps=claim.hmac.compare_digest,
        ) as compare_digest:
            with claim.locked_first_admin_claim(cfg) as transaction:
                assert transaction.matches(secret) is True
                assert transaction.matches(secret + " ") is False
                assert transaction.matches(secret.lower()) is (secret.lower() == secret)
                assert transaction.matches(123) is False
                assert transaction.matches("x" * 257) is False
        assert [call.args for call in compare_digest.call_args_list] == [
            (stored_digest, candidate_digest(candidate))
            for candidate in compared_candidates
        ]
        source = inspect.getsource(claim)
        assert "hmac.compare_digest" in source
        assert ".strip()" not in inspect.getsource(claim.ClaimTransaction.matches)


def test_consumption_erases_digest_and_is_terminal():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        deliveries = []
        _prepare_claim(claim, cfg, deliveries)
        secret = deliveries[0][1]
        with claim.locked_first_admin_claim(cfg) as transaction:
            assert transaction.matches(secret)
            transaction.consume(now=1002.0)
        state = json.loads(Path(claim.claim_state_path(cfg)).read_text(encoding="utf-8"))
        assert state["state"] == "consumed"
        assert state["consumed_at"] == 1002.0
        assert "digest" not in state
        with claim.locked_first_admin_claim(cfg) as transaction:
            assert transaction.state_name == "consumed"
            assert transaction.matches(secret) is False


def test_shared_json_parser_rejects_wrong_media_before_reading_body():
    class TrackedBody(io.BytesIO):
        touched = False

        def read(self, *args, **kwargs):
            self.touched = True
            return super().read(*args, **kwargs)

    body = TrackedBody(b"{}")
    handler = FreqHandler.__new__(FreqHandler)
    handler.headers = {"Content-Type": "text/plain;charset=UTF-8", "Content-Length": "2"}
    handler.rfile = body
    with pytest.raises(Exception, match="application/json"):
        handler._request_body()
    assert body.touched is False


def test_cross_origin_text_plain_fails_before_password_mutation():
    body = {
        "schema": SCHEMA,
        "username": "attacker",
        "password": "attacker-password",
        "client_request_id": "12345678-1234-4123-8123-123456789abc",
    }
    with tempfile.TemporaryDirectory() as root:
        handler = _capturing_handler(
            body,
            headers={
                "Origin": "https://attacker.invalid",
                "Host": "freq.test",
                "Content-Type": "text/plain;charset=UTF-8",
            },
        )
        cfg = _cfg(root)
        with (
            patch("freq.modules.serve._request_is_https", return_value=True),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve._load_users", side_effect=[[], []]),
            patch("freq.modules.serve._setup_store_admin_password", return_value="") as store,
            patch("freq.modules.serve._save_users_error", return_value=""),
            patch("freq.modules.serve.ensure_setup_state", return_value={"setup_id": "setup-1"}),
            patch("freq.modules.serve._setup_session_payload", return_value={"ok": True}),
        ):
            handler._serve_setup_create_admin()
        assert handler._status_code == 400
        assert handler._captured["error"]["code"] == "unsupported_media_type"
        store.assert_not_called()


def test_json_parser_route_set_equals_exact_twelve_callers():
    assert FreqHandler._JSON_BODY_ROUTES == JSON_BODY_ROUTES
    source = inspect.getsource(serve)
    assert source.count("self._request_body()") == 10
    from freq.api import auth

    assert inspect.getsource(auth).count("handler._request_body()") == 2
    assert "/api/auth/logout" not in FreqHandler._JSON_BODY_ROUTES
    assert "/api/setup/status" not in FreqHandler._JSON_BODY_ROUTES
    assert "ltSaveConfig()" in (REPO_ROOT / "docs" / "API-REFERENCE.md").read_text(encoding="utf-8")


def test_login_logout_origin_helper_requires_present_exact_scheme_and_authority():
    def handler(origin: str | None, host="freq.test"):
        headers = {"Host": host}
        if origin is not None:
            headers["Origin"] = origin
        return SimpleNamespace(headers=headers)

    assert same_origin_or_absent(handler("https://freq.test"), require_present=True, is_https=True)
    assert not same_origin_or_absent(handler(None), require_present=True, is_https=True)
    assert not same_origin_or_absent(handler("http://freq.test"), require_present=True, is_https=True)
    assert not same_origin_or_absent(handler("not-an-origin"), require_present=True, is_https=True)
    assert not same_origin_or_absent(handler("https://other.invalid"), require_present=True, is_https=True)


def test_claim_rate_limiter_preserves_per_client_ceiling():
    clock = [1000.0]
    limiter = serve._FirstAdminClaimRateLimiter(clock=lambda: clock[0])
    for _ in range(5):
        limiter.record_invalid("192.0.2.10")
    assert limiter.client_allowed("192.0.2.10") is False
    assert limiter.client_allowed("192.0.2.11") is True
    clock[0] += 301
    assert limiter.client_allowed("192.0.2.10") is True


def test_global_saturation_does_not_prevent_fresh_correct_claim_comparison():
    limiter = serve._FirstAdminClaimRateLimiter(clock=lambda: 1000.0)
    for client in range(10):
        for _ in range(5):
            limiter.record_invalid(f"192.0.2.{client + 1}")
    assert limiter.global_limited() is True
    assert limiter.client_allowed("198.51.100.10") is True
    assert limiter.should_compare("198.51.100.10") is True
    assert limiter.failure_status("198.51.100.10") == 429


@pytest.mark.parametrize(
    ("claim_state", "marker", "users", "expected_code"),
    [
        ("consumed", True, [], "setup_closed"),
        ("consumed", False, [{"username": "operator", "role": "admin"}], "operator_exists"),
        ("consumed", False, [], "claim_consumed"),
    ],
)
def test_consumed_replay_projects_stronger_product_truth_first(claim_state, marker, users, expected_code):
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        deliveries = []
        _prepare_claim(claim, cfg, deliveries)
        with claim.locked_first_admin_claim(cfg) as transaction:
            transaction.consume(now=1001.0)
        handler = _capturing_handler(_claim_body(deliveries[0][1]))
        with (
            patch("freq.modules.serve._request_is_https", return_value=True),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._setup_marker_exists", return_value=marker),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve._load_users", return_value=users),
        ):
            handler._serve_setup_create_admin()
        assert handler._captured["error"]["code"] == expected_code


def test_correct_claim_without_origin_commits_once_and_consumes():
    with tempfile.TemporaryDirectory() as root:
        claim, cfg, _metadata, secret = _seeded_claim(root)
        handler = _capturing_handler(_claim_body(secret))
        assert "Origin" not in handler.headers
        with (
            patch("freq.modules.serve._request_is_https", return_value=True),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._setup_marker_exists", return_value=False),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve._load_users", side_effect=[[], []]),
            patch("freq.modules.serve._setup_store_admin_password", return_value="") as store,
            patch("freq.modules.serve._save_users_error", return_value=""),
            patch("freq.modules.serve.ensure_setup_state", return_value={"setup_id": "setup-1"}),
            patch(
                "freq.modules.serve._setup_session_payload",
                return_value={"ok": True, "session_started": True, "csrf_token": "csrf"},
            ),
        ):
            handler._serve_setup_create_admin()
        assert handler._status_code == 200
        store.assert_called_once()
        with claim.locked_first_admin_claim(cfg) as transaction:
            assert transaction.state_name == "consumed"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "https://attacker.invalid", "Host": "freq.test"},
        {"Origin": "http://freq.test", "Host": "freq.test"},
        {"Origin": "not-an-origin", "Host": "freq.test"},
    ],
)
def test_wrong_claim_has_same_result_for_every_origin_shape(headers):
    with tempfile.TemporaryDirectory() as root:
        claim, cfg, _metadata, _secret = _seeded_claim(root)
        state_path = Path(claim.claim_state_path(cfg))
        before = state_path.read_bytes()
        handler = _capturing_handler(_claim_body("wrong-claim"), headers=headers)
        with (
            patch("freq.modules.serve._request_is_https", return_value=True),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._setup_marker_exists", return_value=False),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve._load_users", return_value=[]),
            patch("freq.modules.serve._setup_store_admin_password") as store,
            patch("freq.modules.serve._save_users_error") as save,
            patch("freq.modules.serve.ensure_setup_state") as setup_state,
            patch("freq.modules.serve._setup_session_payload") as session,
        ):
            handler._serve_setup_create_admin()
        assert handler._status_code == 403
        assert handler._captured["error"]["code"] == "claim_secret_invalid"
        store.assert_not_called()
        save.assert_not_called()
        setup_state.assert_not_called()
        session.assert_not_called()
        assert state_path.read_bytes() == before


def test_failed_admin_persistence_leaves_exact_claim_reusable():
    with tempfile.TemporaryDirectory() as root:
        claim, cfg, _metadata, secret = _seeded_claim(root)
        handler = _capturing_handler(_claim_body(secret))
        with (
            patch("freq.modules.serve._request_is_https", return_value=True),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._setup_marker_exists", return_value=False),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve._load_users", return_value=[]),
            patch("freq.modules.serve._setup_store_admin_password", return_value="vault unavailable"),
        ):
            handler._serve_setup_create_admin()
        assert handler._status_code == 500
        with claim.locked_first_admin_claim(cfg) as transaction:
            assert transaction.state_name == "available"
            assert transaction.matches(secret)


def test_two_concurrent_correct_claims_commit_exactly_one_admin():
    with tempfile.TemporaryDirectory() as root:
        claim, cfg, _metadata, secret = _seeded_claim(root)
        handlers = [
            _capturing_handler(
                {
                    **_claim_body(secret),
                    "client_request_id": f"12345678-1234-4123-8123-123456789ab{index}",
                }
            )
            for index in range(2)
        ]
        registry = []
        registry_guard = threading.Lock()

        def load_users(_cfg):
            with registry_guard:
                return [dict(user) for user in registry]

        def save_users(_cfg, users):
            with registry_guard:
                registry[:] = [dict(user) for user in users]
            return ""

        with (
            patch("freq.modules.serve._request_is_https", return_value=True),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._setup_marker_exists", return_value=False),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve._load_users", side_effect=load_users),
            patch("freq.modules.serve._setup_store_admin_password", return_value="") as store,
            patch("freq.modules.serve._save_users_error", side_effect=save_users),
            patch("freq.modules.serve.ensure_setup_state", return_value={"setup_id": "setup-1"}),
            patch(
                "freq.modules.serve._setup_session_payload",
                return_value={"ok": True, "session_started": True, "csrf_token": "csrf"},
            ),
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda item: item._serve_setup_create_admin(), handlers))
        assert sorted(handler._status_code for handler in handlers) == [200, 409]
        assert [user["username"] for user in registry] == ["operator"]
        store.assert_called_once()
        with claim.locked_first_admin_claim(cfg) as transaction:
            assert transaction.state_name == "consumed"


def test_user_commit_remains_success_when_claim_terminalization_fails_and_replay_closes():
    with tempfile.TemporaryDirectory() as root:
        claim, cfg, _metadata, secret = _seeded_claim(root)
        handler = _capturing_handler(_claim_body(secret))
        registry = []
        critical = []

        def load_users(_cfg):
            return [dict(user) for user in registry]

        def save_users(_cfg, users):
            registry[:] = [dict(user) for user in users]
            return ""

        with (
            patch("freq.modules.serve._request_is_https", return_value=True),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._setup_marker_exists", return_value=False),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve._load_users", side_effect=load_users),
            patch("freq.modules.serve._setup_store_admin_password", return_value=""),
            patch("freq.modules.serve._save_users_error", side_effect=save_users),
            patch("freq.modules.serve.ensure_setup_state", return_value={"setup_id": "setup-1"}),
            patch(
                "freq.modules.serve._setup_session_payload",
                return_value={"ok": True, "session_started": True, "csrf_token": "csrf"},
            ),
            patch.object(claim.ClaimTransaction, "consume", side_effect=claim.ClaimStateError("disk full")),
            patch.object(
                serve.logger,
                "critical",
                side_effect=lambda *args, **kwargs: critical.append((args, kwargs)),
            ),
        ):
            handler._serve_setup_create_admin()
        assert handler._status_code == 200
        assert [user["username"] for user in registry] == ["operator"]
        assert len(critical) == 1
        rendered_warning = json.dumps(critical, default=str)
        assert secret not in rendered_warning
        assert claim.claim_state_path(cfg) not in rendered_warning

        replay = _capturing_handler(_claim_body(secret))
        with (
            patch("freq.modules.serve._request_is_https", return_value=True),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._setup_marker_exists", return_value=False),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve._load_users", side_effect=load_users),
            patch("freq.modules.serve._setup_store_admin_password") as second_store,
        ):
            replay._serve_setup_create_admin()
        assert replay._status_code == 409
        assert replay._captured["error"]["code"] == "operator_exists"
        second_store.assert_not_called()


def test_correct_claim_with_text_plain_is_rejected_before_comparison():
    with tempfile.TemporaryDirectory() as root:
        claim, cfg, _metadata, secret = _seeded_claim(root)
        handler = _capturing_handler(
            _claim_body(secret),
            headers={"Content-Type": "text/plain;charset=UTF-8"},
        )
        with (
            patch("freq.modules.serve._request_is_https", return_value=True),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._setup_store_admin_password") as store,
            patch.object(claim.ClaimTransaction, "matches", wraps=claim.ClaimTransaction.matches) as compare,
        ):
            handler._serve_setup_create_admin()
        assert handler._status_code == 400
        assert handler._captured["error"]["code"] == "unsupported_media_type"
        compare.assert_not_called()
        store.assert_not_called()


def test_startup_observation_failure_aborts_before_listener_construction():
    cfg = SimpleNamespace(
        dashboard_port=8888,
        tls_cert="",
        tls_key="",
        watchdog_enabled=False,
        data_dir="/tmp/f4-data",
    )
    args = SimpleNamespace(port=None)
    with (
        patch.object(FreqHandler, "_load_routes", return_value={}),
        patch("freq.modules.users._load_users", side_effect=PermissionError("users unreadable")),
        patch("freq.modules.serve.start_background_cache"),
        patch("freq.modules.serve._start_embedded_watchdog_if_needed"),
        patch("freq.modules.serve._start_cert_renewal_scheduler_if_needed"),
        patch("freq.modules.serve.ThreadedHTTPServer") as server,
        patch("freq.modules.serve._cleanup_ssh_mux"),
    ):
        result = serve.cmd_serve(cfg, None, args)
    assert result == 1
    server.assert_not_called()


def test_startup_prepares_claim_and_emits_matching_readiness_id_before_listener():
    claim = _claim_module()
    cfg = SimpleNamespace(
        dashboard_port=8888,
        tls_cert="",
        tls_key="",
        watchdog_enabled=False,
        data_dir="/tmp/f4-data",
        conf_dir="/tmp/f4-conf",
    )
    args = SimpleNamespace(port=None)
    order = []
    httpd = SimpleNamespace(
        socket=object(),
        serve_forever=lambda: None,
        server_close=lambda: None,
    )

    def prepare(*_args, **_kwargs):
        order.append("prepare")
        return {"state": "available", "claim_id": "claim-id", "generated": True, "delivered": True}

    def construct(*_args, **_kwargs):
        order.append("listener")
        return httpd

    with (
        patch.object(FreqHandler, "_load_routes", return_value={}),
        patch("freq.modules.users._load_users", return_value=[]),
        patch("freq.modules.serve._setup_marker_exists", return_value=False),
        patch("freq.modules.serve.prepare_first_admin_claim", side_effect=prepare, create=True),
        patch("freq.modules.serve.start_background_cache"),
        patch("freq.modules.serve._start_embedded_watchdog_if_needed"),
        patch("freq.modules.serve._start_cert_renewal_scheduler_if_needed"),
        patch("freq.modules.serve.ThreadedHTTPServer", side_effect=construct),
        patch("freq.modules.serve.signal.signal"),
        patch("freq.modules.serve._cleanup_ssh_mux"),
        patch("builtins.print") as output,
    ):
        assert serve.cmd_serve(cfg, None, args) == 0
    assert order == ["prepare", "listener"]
    rendered = "\n".join(" ".join(map(str, call.args)) for call in output.call_args_list)
    assert "claim-id" in rendered
    assert "fixture-raw-secret" not in rendered
    assert claim.__name__ == "freq.core.first_admin_claim"


def test_operator_claim_field_and_submission_contract_are_explicit_and_secret_safe():
    html = (REPO_ROOT / "freq/data/web/setup.html").read_text(encoding="utf-8")
    js = (REPO_ROOT / "freq/data/web/js/setup.js").read_text(encoding="utf-8")
    form = re.search(r'<form id="operator-form"(?P<attrs>[^>]*)>(?P<body>.*?)</form>', html, re.S)
    assert form
    assert 'method="post"' in form.group("attrs")
    assert "action=" not in form.group("attrs")
    claim_input = re.search(r'<input id="operator-claim"(?P<attrs>[^>]*)>', form.group("body"))
    assert claim_input
    attrs = claim_input.group("attrs")
    for required in (
        'type="password"',
        'autocomplete="off"',
        'autocapitalize="none"',
        'spellcheck="false"',
        'aria-describedby="operator-claim-help"',
        'data-api-field="claim_secret"',
        "required",
    ):
        assert required in attrs
    assert re.search(r"(?:^|\s)name=", attrs) is None
    assert "First-boot claim secret" in form.group("body")
    assert "newest one-time claim emitted for the currently" in form.group("body")
    create = js.split("function createOperator(event){", 1)[1].split("function verifySession", 1)[0]
    assert "claim_secret:$('operator-claim').value" in create
    assert "trim('operator-claim')" not in create
    assert "$('operator-claim').value=''" in create
    assert "Origin" not in create


def test_direct_resume_helper_stays_origin_free_and_uses_injected_claim():
    script = r"""
const { createFirstAdmin } = require('./tests/support/zero_state_failure_resume');
const captured = [];
const context = { request: { post: async (url, options) => {
  captured.push({ url, options });
  return { status: () => 200, text: async () => JSON.stringify({ ok: true }) };
} } };
(async () => {
  const claim = '  Exact-Mixed_Case-Claim  ';
  await createFirstAdmin(context, 'https://freq.test:8888', claim);
  const request = captured[0];
  process.stdout.write(JSON.stringify({ count: captured.length, request, claim }));
})().catch(error => { console.error(error); process.exit(1); });
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    observed = json.loads(result.stdout)
    assert observed["count"] == 1
    assert observed["request"]["url"] == "https://freq.test:8888/api/setup/create-admin"
    options = observed["request"]["options"]
    assert set(options) == {"data"}
    assert set(options["data"]) == {
        "schema",
        "username",
        "password",
        "claim_secret",
        "client_request_id",
    }
    assert options["data"]["claim_secret"] == observed["claim"]
    assert json.dumps(options).count("claim_secret") == 1
    assert "headers" not in options
    assert "Origin" not in json.dumps(options)


def test_openapi_and_human_contract_publish_claim_json_and_local_recovery_truth():
    from tests.test_openapi_truth import _get_openapi_spec

    spec = _get_openapi_spec()
    operation = spec["paths"]["/api/setup/create-admin"]["post"]
    assert operation["security"] == []
    assert not any(parameter.get("name", "").lower() == "origin" for parameter in operation.get("parameters", []))
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert set(schema["required"]) == {
        "schema",
        "username",
        "password",
        "claim_secret",
        "client_request_id",
    }
    assert schema["properties"]["claim_secret"]["writeOnly"] is True
    assert schema["properties"]["claim_secret"]["format"] == "password"
    for route in JSON_BODY_ROUTES:
        assert set(spec["paths"][route]["post"]["requestBody"]["content"]) == {"application/json"}
    for route in ("/api/auth/login", "/api/auth/logout"):
        origin = [
            parameter
            for parameter in spec["paths"][route]["post"].get("parameters", [])
            if parameter.get("name", "").lower() == "origin"
        ]
        assert len(origin) == 1
        assert origin[0]["in"] == "header"
        assert origin[0]["required"] is True
        assert origin[0]["schema"]["type"] == "string"

    docs = [
        (REPO_ROOT / path).read_text(encoding="utf-8")
        for path in ("docs/API-REFERENCE.md", "docs/ZERO-STATE-WEB-API-CONTRACT.md")
    ]
    joined_docs = "\n".join(docs)

    def operation_section(method, route):
        heading = re.compile(rf"(?ms)^###\s+`?{re.escape(method)}\s+{re.escape(route)}`?\s*$\n(.*?)(?=^###\s|\Z)")
        sections = [match.group(1) for document in docs for match in heading.finditer(document)]
        assert sections, f"missing exact human-contract section for {method} {route}"
        return "\n".join(sections)

    for route in JSON_BODY_ROUTES:
        assert "application/json" in operation_section("POST", route).lower()
    for route in ("/api/auth/login", "/api/auth/logout"):
        auth_section = operation_section("POST", route)
        assert "Origin is required" in auth_section
    create_section = operation_section("POST", "/api/setup/create-admin")
    assert "Origin is not required" in create_section
    for forbidden in (
        "Origin is required",
        "required Origin header",
        "must send Origin",
        "must include Origin",
    ):
        assert forbidden not in create_section
    for phrase in (
        "browser and programmatic",
        "claim_secret",
        "most recently emitted",
        "first-admin claim reset",
        "pve-freq-setup.service",
        "ltSaveConfig()",
    ):
        assert phrase in joined_docs
