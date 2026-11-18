"""Original HTTP/auth/qualification/power/SQLite with fictional PVE GET/POST ports.

Certificates, credentials and manifests are temporary test-owned data. No socket,
DNS, real credential or provider request is permitted. This is composition
evidence, never native target/qualification or power acceptance.
"""
import contextlib
import datetime
import hashlib
import io
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from freq.api import auth, lab_guest, lab_qualification
from freq.modules import serve
from freq.services import lab_guest_power, lab_power_qualification
from freq.services.lab_guest_registration import RegistrationError, load_registration
from freq.services.lab_pve_transport import LabPveTransport
from tests.test_lab_guest_api import TOKEN, handler, response, session
from tests.test_lab_guest_registration import synthetic_ca  # noqa: F401


def stamp(instant):
    return datetime.datetime.fromtimestamp(instant, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture
def composition(tmp_path, synthetic_ca, monkeypatch):
    now = time.time()
    for name in ("conf", "data"):
        (tmp_path / name).mkdir(mode=0o700)
    token, ca = tmp_path / "fictional-token", tmp_path / "fictional-ca.pem"
    token.write_bytes(b"FICTIONAL-COMPOSITION-TOKEN-NOT-LIVE\n")
    token.chmod(0o600)
    ca.write_bytes(synthetic_ca)
    ca.chmod(0o644)
    base = {
        "schema": "pve-freq-lab-guest-v1", "registration_id": "1" * 32,
        "qualified_at": stamp(now - 7200), "expires_at": stamp(now - 3600),
        "lab_only": True, "estate": "fictional-estate", "provider": "pve.example.invalid",
        "node": "fictional-node", "guest_type": "qemu", "vmid": 5000, "name": "fictional-guest",
        "instance_uuid": "12345678-1234-5678-9123-123456789abc", "allowed_actions": ["status"],
        "credentials": {"token_id": "fictional@pve!power", "token_secret_file": str(token), "ca_file": str(ca)},
        "qualification_ref": "fictional-composition-only",
    }
    manifest = tmp_path / "conf/lab-guest.json"
    manifest.write_text(json.dumps(base))
    manifest.chmod(0o600)
    base_revision = hashlib.sha256(manifest.read_bytes()).hexdigest()
    policy_document = {"schema": "pve-freq-lab-power-policy-v1", "enabled": True,
        "registration_id": base["registration_id"], "configuration_revision": base_revision,
        "allowed_actions": ["start", "shutdown"], "window_seconds": 900,
        "credential_expires_at": stamp(now + 7200)}
    policy = tmp_path / "conf/lab-power-policy.json"

    def write_policy():
        policy.write_text(json.dumps(policy_document))
        policy.chmod(0o600)

    write_policy()
    cfg = SimpleNamespace(conf_dir=str(tmp_path / "conf"), data_dir=str(tmp_path / "data"))
    case = SimpleNamespace(cfg=cfg, root=tmp_path, base=base, base_revision=base_revision,
        policy=policy, policy_document=policy_document, write_policy=write_policy,
        calls=[], current_state="stopped", task_state="running", task_exit=None,
        held_upid=None, held_action=None, hook=None, clock_value=None)
    # Only core qualification/power clocks move. Auth expiry keeps real time.
    case.clock = lambda: time.time() if case.clock_value is None else case.clock_value
    case.database = tmp_path / "data/lab-power/operations.sqlite3"

    def no_transaction(scope, method):
        with contextlib.closing(sqlite3.connect(case.database, timeout=0, isolation_level=None)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if scope == "qualification":
                assert connection.execute("SELECT COUNT(*) FROM qualification_requests WHERE state='preparing'").fetchone()[0] == 1
            if method == "POST":
                assert connection.execute("SELECT phase,active FROM operations WHERE active=1").fetchone() == ("dispatching", 1)
            connection.execute("ROLLBACK")

    class Provider(LabPveTransport):
        def __init__(self, registration, scope):
            super().__init__(registration)
            self.scope = scope

        def port(self, method, suffix, value):
            if self.current is not None:
                assert self.current() is True
            no_transaction(self.scope, method)
            case.calls.append((self.scope, method, suffix, self.registration.revision))
            if case.hook:
                case.hook(self.scope, suffix)
            return value

        def get_config(self):
            return self.port("GET", "/config", {"name": base["name"], "smbios1": "uuid=" + base["instance_uuid"]})

        def get_status(self):
            return self.port("GET", "/status/current", {"status": case.current_state})

        def get_permissions(self):
            return self.port("GET", "/access/permissions?path=/vms/5000",
                             {"/vms/5000": {"VM.Audit": 0, "VM.PowerMgmt": 0}})

        def submit(self, action):
            if self.before_submit is not None:
                self.before_submit()
            assert action in ("start", "shutdown")
            case.held_action = action
            kind = "qmstart" if action == "start" else "qmshutdown"
            case.held_upid = "UPID:fictional-node:00000001:00000002:12345678:" + kind + ":5000:fictional@pve!power:"
            return self.port("POST", "/status/" + action, case.held_upid)

        def get_task(self, upid):
            assert upid == case.held_upid, "only the original retained provider task may be read"
            principal, token_id = base["credentials"]["token_id"].split("!", 1)
            data = {"upid": upid, "node": base["node"], "id": "5000", "user": principal, "tokenid": token_id,
                    "type": "qmstart" if case.held_action == "start" else "qmshutdown", "status": case.task_state}
            if case.task_exit is not None:
                data["exitstatus"] = case.task_exit
            return self.port("GET", "/tasks/original-retained-task/status", data)

    qualification_class = lab_power_qualification.LabPowerQualification
    power_class = lab_guest_power.RegisteredLabPower

    def qualification_factory(selected_cfg, *, still_current):
        assert selected_cfg is cfg
        return qualification_class(cfg, still_current=still_current, clock=case.clock,
            transport_factory=lambda registration: Provider(registration, "qualification"))

    def power_factory(selected_cfg, **kwargs):
        assert selected_cfg is cfg
        return power_class(cfg, clock=case.clock,
            transport_factory=lambda registration: Provider(registration, "power"), **kwargs)

    # Preserve all real qualification/factory/SQLite logic through both aliases.
    monkeypatch.setattr(lab_power_qualification, "LabPowerQualification", qualification_factory)
    monkeypatch.setattr(lab_qualification, "LabPowerQualification", qualification_factory)
    monkeypatch.setattr(lab_guest, "RegisteredLabPower", power_factory)
    for module in (lab_guest, lab_qualification):
        monkeypatch.setattr(module, "load_config", lambda: cfg)
    monkeypatch.setattr(auth, "_auth_tokens", {TOKEN: session("admin")})
    monkeypatch.setattr(auth, "_auth_lock", threading.RLock())
    monkeypatch.setattr(auth, "request_is_https", lambda value: value._test_https)
    monkeypatch.setattr(serve.FreqHandler, "_ROUTE_REGISTRY", None)
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, Mock(side_effect=AssertionError("network forbidden")))
    monkeypatch.setattr(subprocess, "Popen", Mock(side_effect=AssertionError("process forbidden")))
    monkeypatch.setattr(LabPveTransport, "_native", Mock(side_effect=AssertionError("native provider forbidden")))
    return case


def public(document, case):
    encoded = json.dumps(document)
    for secret in (TOKEN, case.base["credentials"]["token_id"], str(case.root), case.base["instance_uuid"],
                   "UPID:", "FICTIONAL-COMPOSITION-TOKEN", '"actor"', '"request_key"', '"credentials"'):
        assert secret not in encoded
    if case.database.exists():
        with contextlib.closing(sqlite3.connect(case.database)) as database:
            for actor, request_key in database.execute("SELECT actor,request_key FROM qualification_requests"):
                assert actor not in encoded and request_key not in encoded
            for actor, request_key, upid in database.execute("SELECT actor,request_key,upid FROM operations"):
                assert actor not in encoded and request_key not in encoded
                assert upid is None or upid not in encoded


def dispatch(case, path, method="GET", body=None, cookie=TOKEN):
    value = handler(path, method, body=body, cookie=cookie)
    value._dispatch()
    document, status = response(value)
    public(document, case)
    return document, status


def get_metadata(case, cookie=TOKEN):
    document, status = dispatch(case, "/api/lab/window", cookie=cookie)
    assert status == 200
    return document


def qualify(case, key="fictional-qualification"):
    metadata = get_metadata(case)
    body = {"target_ref": metadata["target"]["ref"],
            "configuration_revision": metadata["target"]["configuration_revision"],
            "policy_revision": metadata["policy"]["revision"], "request_key": key}
    document, status = dispatch(case, "/api/lab/window", "POST", body)
    assert status == 201 and document["window"]["state"] == "active"
    return document


def guest(case, cookie=TOKEN):
    document, status = dispatch(case, "/api/lab/guest", cookie=cookie)
    assert status == 200
    return document


def power_body(current, key="fictional-power"):
    return {"target_ref": current["target"]["ref"],
            "registration_revision": current["target"]["registration_revision"],
            "action": "start", "expected_state": "stopped", "request_key": key}


def completed_power(case):
    grant = qualify(case)
    current = guest(case)
    assert current["target"]["registration_revision"] == grant["window"]["registration_revision"]
    posted, status = dispatch(case, "/api/lab/power", "POST", power_body(current))
    assert status == 202 and posted["operation"]["phase"] == "acknowledged"
    reference = posted["operation"]["ref"]
    pending, status = dispatch(case, "/api/lab/operations/" + reference)
    assert status == 200 and pending["operation"]["task"]["state"] == "running"
    assert pending["operation"]["observation"]["state"] == "stopped"
    case.task_state, case.task_exit, case.current_state = "stopped", "OK", "running"
    terminal, status = dispatch(case, "/api/lab/operations/" + reference)
    assert status == 200 and terminal["operation"]["phase"] == "succeeded"
    assert terminal["operation"]["task"] == {"state": "succeeded", "exit": "OK"}
    assert terminal["operation"]["observation"]["state"] == "running"
    return grant, reference, terminal


def test_expired_base_still_has_metadata_and_qualification_commits_three_get_grant(composition):
    case = composition
    with pytest.raises(RegistrationError, match="^registration_expired$"):
        load_registration(case.cfg)
    metadata = get_metadata(case)
    assert metadata["target"]["configuration_revision"] == case.base_revision
    assert metadata["policy"]["enabled"] is True and metadata["can_request"] is True
    assert metadata["window"] is None and metadata["busy"] is False
    assert case.calls == []
    grant = qualify(case)
    assert [(scope, method, path) for scope, method, path, _ in case.calls] == [
        ("qualification", "GET", "/config"), ("qualification", "GET", "/status/current"),
        ("qualification", "GET", "/access/permissions?path=/vms/5000")]
    assert grant["window"]["registration_revision"] != case.base_revision
    with contextlib.closing(sqlite3.connect(case.database)) as database:
        row = database.execute("SELECT state,effective_revision,qualified_at,expires_at FROM qualification_requests").fetchone()
        assert row[0:2] == ("active", grant["window"]["registration_revision"])
        assert row[3] - row[2] == 900
        assert database.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0
    current = guest(case)
    assert current["capabilities"] == {"lab_only": True, "actions": ["start", "shutdown"]}
    assert current["target"]["registration_revision"] == grant["window"]["registration_revision"]


def test_original_power_task_record_and_fresh_guest_share_effective_binding(composition):
    case = composition
    grant, reference, terminal = completed_power(case)
    assert terminal["operation"]["target_ref"] == grant["target"]["ref"]
    assert terminal["operation"]["retired"] is False
    assert terminal["operation"]["registration_revision"] == grant["window"]["registration_revision"]
    count = len(case.calls)
    fresh = guest(case)
    assert len(case.calls) == count + 2
    assert fresh["observation"]["state"] == "running" and fresh["busy"] is False
    assert fresh["target"]["registration_revision"] == terminal["operation"]["registration_revision"]
    assert len([row for row in case.calls if row[1] == "POST"]) == 1
    with contextlib.closing(sqlite3.connect(case.database)) as database:
        assert database.execute("SELECT phase,active,upid FROM operations WHERE id=?", (reference,)).fetchone() == (
            "succeeded", 0, case.held_upid)


def test_other_admin_session_has_diagnostic_status_but_no_foreign_grant(composition):
    case = composition
    grant = qualify(case)
    creator = guest(case)
    auth._auth_tokens["fictional-other-admin"] = session("admin")
    other_window = get_metadata(case, "fictional-other-admin")
    assert other_window["window"] is None and other_window["can_request"] is True
    other_guest = guest(case, "fictional-other-admin")
    assert other_guest["capabilities"]["actions"] == []
    assert other_guest["target"]["registration_revision"] != grant["window"]["registration_revision"]
    before = len(case.calls)
    denied, status = dispatch(case, "/api/lab/power", "POST", power_body(creator), cookie="fictional-other-admin")
    assert status == 409 and denied["error"] == "registration_changed"
    assert len(case.calls) == before


def test_role_demotion_during_original_preflight_prevents_power_write(composition):
    case = composition
    qualify(case)
    current = guest(case)
    def demote(scope, path):
        if scope == "power" and path == "/status/current":
            auth._auth_tokens[TOKEN]["role"] = "operator"
    case.hook = demote
    denied, status = dispatch(case, "/api/lab/power", "POST", power_body(current))
    assert status == 403 and denied["error"] == "session_retired"
    assert not any(row[1] == "POST" for row in case.calls)
    case.hook = None
    diagnostic = guest(case)
    assert diagnostic["capabilities"]["actions"] == []
    assert get_metadata(case)["window"]["state"] == "retired"


def test_changed_policy_strips_old_grant_before_any_provider_write(composition):
    case = composition
    qualify(case)
    current = guest(case)
    case.policy_document["enabled"] = False
    case.write_policy()
    before = len(case.calls)
    denied, status = dispatch(case, "/api/lab/power", "POST", power_body(current))
    assert status == 409 and denied["error"] == "registration_changed"
    assert len(case.calls) == before
    assert guest(case)["capabilities"]["actions"] == []
    assert get_metadata(case)["window"]["state"] == "retired"


@pytest.mark.parametrize("revocation", ["disabled", "missing", "invalid", "changed_base"])
@pytest.mark.parametrize("first_observation", ["window", "guest"])
def test_observed_owner_revocation_survives_identical_file_restoration(composition, revocation, first_observation):
    case = composition
    original = qualify(case)
    old_guest = guest(case)
    manifest = Path(case.cfg.conf_dir) / "lab-guest.json"
    saved_policy, saved_base = case.policy.read_bytes(), manifest.read_bytes()
    if revocation == "disabled":
        case.policy_document["enabled"] = False
        case.write_policy()
    elif revocation == "missing":
        case.policy.unlink()
    elif revocation == "invalid":
        case.policy.write_bytes(b'{"schema":"fictional-invalid-policy"}')
    else:
        changed = json.loads(saved_base)
        changed["qualification_ref"] = "fictional-owner-replaced-configuration"
        manifest.write_text(json.dumps(changed))

    if first_observation == "window":
        before_observation = len(case.calls)
        retired = get_metadata(case)
        assert retired["window"]["ref"] == original["window"]["ref"]
        assert retired["window"]["state"] == "retired"
        assert retired["can_request"] is False
        assert len(case.calls) == before_observation, "owner revocation observation is local"
    # In the guest-first cases, do not read metadata until after restoration
    # and the stale power intent. Guest observation must retire authority too.
    diagnostic, status = dispatch(case, "/api/lab/guest")
    if revocation == "disabled":
        assert status == 200 and diagnostic["capabilities"]["actions"] == []
    else:
        # Missing policy falls back to the expired status-only base; invalid
        # policy/config mismatches fail closed instead of granting a window.
        assert status != 200 or diagnostic["capabilities"]["actions"] == []

    manifest.write_bytes(saved_base)
    case.policy.write_bytes(saved_policy)
    case.policy.chmod(0o600)
    assert manifest.read_bytes() == saved_base and case.policy.read_bytes() == saved_policy

    # Attempt the old revision before any restored GET can mask a dispatch bug.
    before_dispatch = len(case.calls)
    refused, status = dispatch(case, "/api/lab/power", "POST",
                               power_body(old_guest, "fictional-after-owner-revocation"))
    assert status == 409, (revocation, status, refused)
    assert len(case.calls) == before_dispatch, "retired authority must refuse before any provider I/O"
    restored = get_metadata(case)
    assert restored["window"]["ref"] == original["window"]["ref"]
    assert restored["window"]["state"] == "retired"
    assert restored["window"]["registration_revision"] == original["window"]["registration_revision"]
    assert restored["can_request"] is True
    current = guest(case)
    assert current["capabilities"]["actions"] == []
    assert current["target"]["registration_revision"] != old_guest["target"]["registration_revision"]
    with contextlib.closing(sqlite3.connect(case.database)) as database:
        assert database.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0

    # Restoration permits a new explicit intent, never resurrection or replay
    # of the authority withdrawn by the observed owner change.
    before_qualification = len(case.calls)
    replacement = qualify(case, "fictional-new-after-owner-revocation")
    assert replacement["window"]["ref"] != original["window"]["ref"]
    assert replacement["window"]["registration_revision"] != original["window"]["registration_revision"]
    assert [(scope, method, path) for scope, method, path, _ in case.calls[before_qualification:]] == [
        ("qualification", "GET", "/config"), ("qualification", "GET", "/status/current"),
        ("qualification", "GET", "/access/permissions?path=/vms/5000")]
    assert not any(row[1] == "POST" for row in case.calls)


def test_policy_change_during_power_preflight_rejects_before_provider_write(composition):
    case = composition
    qualify(case)
    current = guest(case)
    def replace_policy(scope, path):
        if scope == "power" and path == "/status/current":
            case.policy_document["credential_expires_at"] = stamp(time.time() + 7300)
            case.write_policy()
    case.hook = replace_policy
    denied, status = dispatch(case, "/api/lab/power", "POST", power_body(current))
    assert status == 409 and denied["operation"]["phase"] == "rejected"
    assert denied["operation"]["error"] == "registration_changed"
    assert denied["operation"]["retired"] is True and denied["operation"]["target_ref"] is None
    assert not any(row[1] == "POST" for row in case.calls)


def test_terminal_projection_rechecks_effective_factory_without_new_provider_read(composition):
    case = composition
    grant, reference, terminal = completed_power(case)
    before = len(case.calls)
    replay, status = dispatch(case, "/api/lab/operations/" + reference)
    assert status == 200 and replay["operation"]["retired"] is False
    assert replay["operation"]["target_ref"] == grant["target"]["ref"]
    assert len(case.calls) == before
    case.policy_document["credential_expires_at"] = stamp(time.time() + 7300)
    case.write_policy()
    retired, status = dispatch(case, "/api/lab/operations/" + reference)
    assert status == 200 and retired["operation"]["target_ref"] is None
    assert retired["operation"]["retired"] is True
    assert retired["operation"]["phase"] == terminal["operation"]["phase"] == "succeeded"
    assert retired["operation"]["observation"] == terminal["operation"]["observation"]
    assert len(case.calls) == before


def test_lost_qualification_response_get_recovers_current_session_grant_without_retry(composition):
    case = composition
    metadata = get_metadata(case)
    value = handler("/api/lab/window", "POST", body={
        "target_ref": metadata["target"]["ref"], "configuration_revision": metadata["target"]["configuration_revision"],
        "policy_revision": metadata["policy"]["revision"], "request_key": "fictional-lost-intent"})
    class Lost(io.BytesIO):
        def write(self, _data): raise BrokenPipeError("fictional-lost-response")
    value.wfile = Lost()
    value._dispatch()
    assert value.send_response.call_count == 1 and value.close_connection
    value._json_response.assert_not_called()
    before = len(case.calls)
    # GET exposes current session authority, not a request-key acknowledgement.
    recovered = get_metadata(case)
    assert recovered["window"]["state"] == "active" and recovered["can_request"] is False
    assert len(case.calls) == before == 3
    current = guest(case)
    assert current["target"]["registration_revision"] == recovered["window"]["registration_revision"]
    with contextlib.closing(sqlite3.connect(case.database)) as database:
        assert database.execute("SELECT COUNT(*) FROM qualification_requests").fetchone()[0] == 1
        assert database.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0
    assert not any(row[1] == "POST" for row in case.calls)


def test_acknowledged_task_can_settle_when_window_expires_mid_poll(composition):
    case = composition
    grant = qualify(case)
    current = guest(case)
    granted_revision = grant["window"]["registration_revision"]
    posted, status = dispatch(case, "/api/lab/power", "POST", power_body(current))
    assert status == 202 and posted["operation"]["phase"] == "acknowledged"
    reference = posted["operation"]["ref"]
    expires = datetime.datetime.fromisoformat(grant["window"]["expires_at"].replace("Z", "+00:00")).timestamp()
    case.clock_value = expires - 0.5
    case.task_state, case.task_exit, case.current_state = "stopped", "OK", "running"
    crossed = []

    def cross_expiry(scope, path):
        if scope == "power" and path == "/tasks/original-retained-task/status":
            assert case.clock() < expires
            case.clock_value = expires + 0.5
            crossed.append(True)

    case.hook = cross_expiry
    before = len(case.calls)
    terminal, status = dispatch(case, "/api/lab/operations/" + reference)
    assert crossed == [True] and status == 200
    operation = terminal["operation"]
    assert operation["phase"] == "succeeded"
    assert operation["task"] == {"state": "succeeded", "exit": "OK"}
    assert operation["observation"]["state"] == "running"
    assert operation["registration_revision"] == granted_revision
    assert operation["target_ref"] == current["target"]["ref"] and operation["retired"] is False
    assert [row[1:3] for row in case.calls[before:]] == [
        ("GET", "/config"), ("GET", "/tasks/original-retained-task/status"), ("GET", "/status/current")]
    assert len([row for row in case.calls if row[1] == "POST"]) == 1
    with contextlib.closing(sqlite3.connect(case.database)) as database:
        assert database.execute("SELECT phase,active,upid FROM operations WHERE id=?", (reference,)).fetchone() == (
            "succeeded", 0, case.held_upid)

    case.hook = None
    count = len(case.calls)
    metadata = get_metadata(case)
    assert metadata["window"]["state"] == "expired"
    assert metadata["window"]["registration_revision"] == granted_revision
    assert len(case.calls) == count, "expiry metadata must not poll or submit to the provider"
    fresh = guest(case)
    assert fresh["observation"]["state"] == "running"
    assert fresh["capabilities"]["actions"] == [] and fresh["busy"] is False
    assert fresh["target"]["registration_revision"] == granted_revision
    assert fresh["target"]["qualified_at"] == grant["window"]["qualified_at"]
    assert fresh["target"]["expires_at"] == grant["window"]["expires_at"]
    after_fresh = len(case.calls)
    repeated, status = dispatch(case, "/api/lab/operations/" + reference)
    assert status == 200 and repeated["operation"]["retired"] is False
    assert repeated["operation"]["observation"] == operation["observation"]
    assert len(case.calls) == after_fresh


def test_new_power_intent_after_expiry_cannot_reuse_read_witness_as_authority(composition):
    case = composition
    grant = qualify(case)
    current = guest(case)
    expires = datetime.datetime.fromisoformat(grant["window"]["expires_at"].replace("Z", "+00:00")).timestamp()
    case.clock_value = expires + 1
    before = len(case.calls)
    denied, status = dispatch(case, "/api/lab/power", "POST", power_body(current, key="fictional-new-after-expiry"))
    assert status == 409 and denied["error"] == "dispatch_rejected"
    assert len(case.calls) == before, "expired mutation rights must refuse before provider I/O"
    with contextlib.closing(sqlite3.connect(case.database)) as database:
        assert database.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0
    diagnostic = guest(case)
    assert diagnostic["capabilities"]["actions"] == []
    assert diagnostic["target"]["registration_revision"] == current["target"]["registration_revision"]
    assert diagnostic["target"]["expires_at"] == current["target"]["expires_at"]
    assert not any(row[1] == "POST" for row in case.calls)
