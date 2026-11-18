"""Qualification controls: original SQLite/manifest readers, fictional GET ports."""
import contextlib
import datetime
import hashlib
import json
import socket
import sqlite3
import ssl
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from freq.services import lab_power_qualification as qualification
from freq.services.lab_guest_registration import load_registration
from freq.services.lab_power_store import LabPowerStore
from freq.services.lab_pve_transport import LabPveTransport

ACTOR, OTHER = "a" * 64, "b" * 64
NOW = datetime.datetime(2026, 11, 13, 12, tzinfo=datetime.timezone.utc).timestamp()


def stamp(value):
    return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture(scope="module")
def public_ca():
    return ssl.DER_cert_to_PEM_cert(ssl.create_default_context().get_ca_certs(binary_form=True)[0]).encode()


@pytest.fixture
def fixture(tmp_path, public_ca, monkeypatch):
    for name in ("conf", "data"):
        (tmp_path / name).mkdir(mode=0o700)
    secret, ca = tmp_path / "fictional-token", tmp_path / "public-ca.pem"
    secret.write_bytes(b"FICTIONAL-QUALIFICATION-TOKEN-NOT-LIVE\n")
    secret.chmod(0o600)
    ca.write_bytes(public_ca)
    ca.chmod(0o644)
    cfg = SimpleNamespace(conf_dir=str(tmp_path / "conf"), data_dir=str(tmp_path / "data"))
    document = {"schema": "pve-freq-lab-guest-v1", "registration_id": "1" * 32,
                "qualified_at": stamp(NOW - 3600), "expires_at": stamp(NOW + 600),
                "lab_only": True, "estate": "fictional-estate", "provider": "fictional.invalid",
                "node": "fictional-node", "guest_type": "qemu", "vmid": 5000,
                "name": "fictional-guest", "instance_uuid": "12345678-1234-5678-9123-123456789abc",
                "allowed_actions": ["status"], "qualification_ref": "fictional-evidence",
                "credentials": {"token_id": "fictional@pve!reader", "token_secret_file": str(secret), "ca_file": str(ca)}}
    manifest = tmp_path / "conf" / "lab-guest.json"
    manifest.write_text(json.dumps(document))
    manifest.chmod(0o600)
    policy_document = {"schema": "pve-freq-lab-power-policy-v1", "enabled": True,
                       "registration_id": "1" * 32, "configuration_revision": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                       "allowed_actions": ["start", "shutdown"], "window_seconds": 900,
                       "credential_expires_at": stamp(NOW + 7200)}
    policy = tmp_path / "conf" / "lab-power-policy.json"

    def write_policy():
        policy.write_text(json.dumps(policy_document))
        policy.chmod(0o600)

    write_policy()
    owner = SimpleNamespace(cfg=cfg, root=tmp_path, manifest=manifest, document=document,
                            policy=policy, policy_document=policy_document, write_policy=write_policy,
                            clock=[NOW], mono=[1000.0], current=[True], calls=[], hooks={})

    class Provider:
        def __init__(self, registration):
            owner.transport = self
            self.registration = registration
        def call(self, kind, value):
            owner.calls.append(kind)
            assert self.current() is True and self.deadline <= owner.mono[0] + 10
            with contextlib.closing(sqlite3.connect(str(tmp_path / "data/lab-power/operations.sqlite3"), timeout=0, isolation_level=None)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                assert connection.execute("SELECT COUNT(*) FROM qualification_requests WHERE state='preparing'").fetchone()[0] >= 1
                connection.execute("ROLLBACK")
            return owner.hooks[kind]() if kind in owner.hooks else value
        def get_config(self):
            return self.call("config", {"name": "fictional-guest", "smbios1": "uuid=" + owner.document["instance_uuid"]})
        def get_status(self):
            return self.call("status", {"status": "stopped"})
        def get_permissions(self):
            return self.call("permissions", {"/vms/5000": {"VM.Audit": 0, "VM.PowerMgmt": 0}})
        def submit(self, *_args):
            raise AssertionError("native POST forbidden")

    def service():
        return qualification.LabPowerQualification(cfg, still_current=lambda: owner.current[0],
                    clock=lambda: owner.clock[0], monotonic=lambda: owner.mono[0], transport_factory=Provider)

    owner.service = service
    owner.q = service()
    owner.request = lambda key="fictional-request": {"target_ref": "1" * 32,
                 "configuration_revision": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                 "policy_revision": hashlib.sha256(policy.read_bytes()).hexdigest(), "request_key": key}
    owner.base = lambda: load_registration(cfg, now=owner.clock[0], allow_expired=True)
    owner.target = lambda: json.dumps({key: getattr(owner.base(), key) for key in (
        "estate", "provider", "node", "guest_type", "vmid", "instance_uuid")}, sort_keys=True, separators=(",", ":"))
    monkeypatch.setattr(socket, "socket", Mock(side_effect=AssertionError("network forbidden")))
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=AssertionError("network forbidden")))
    monkeypatch.setattr(socket, "getaddrinfo", Mock(side_effect=AssertionError("DNS forbidden")))
    monkeypatch.setattr(LabPveTransport, "_native", Mock(side_effect=AssertionError("native provider forbidden")))
    return owner


def error(code, call):
    with pytest.raises(qualification.QualificationError) as caught:
        call()
    assert caught.value.code == code and str(caught.value) == code


def test_metadata_exact_private_projection_and_no_provider_reads(fixture):
    result = fixture.q.inspect(ACTOR, can_request=True)
    assert set(result) == {"schema", "target", "policy", "window", "busy", "can_request", "reason"}
    assert result["schema"] == "pve-freq-lab-window-v1"
    assert set(result["target"]) == {"ref", "configuration_revision", "estate", "source", "node", "kind", "vmid", "name"}
    assert result["policy"] == {"enabled": True, "revision": fixture.request()["policy_revision"],
                                "duration_seconds": 900, "audience": "original_session"}
    assert result["window"] is None and result["busy"] is False and result["can_request"] is True
    raw = json.dumps(result)
    for private in (ACTOR, fixture.document["instance_uuid"], "fictional@pve!reader", str(fixture.root), "FICTIONAL-QUALIFICATION-TOKEN"):
        assert private not in raw
    assert fixture.calls == []


def test_new_window_commits_after_three_gets_and_effective_registration_is_stable(fixture):
    dto, status = fixture.q.qualify(ACTOR, fixture.request(), can_request=True)
    assert status == 201 and fixture.calls == ["config", "status", "permissions"]
    window = dto["window"]
    assert set(window) == {"ref", "state", "registration_revision", "qualified_at", "expires_at", "error"}
    assert window["state"] == "active" and window["qualified_at"] == stamp(NOW) and window["expires_at"] == stamp(NOW + 900)
    effective = fixture.q.effective_registration(ACTOR, can_request=True)
    assert effective.allowed_actions == ("status", "start", "shutdown")
    assert effective.revision == window["registration_revision"] != fixture.base().revision
    fixture.clock[0] += 30
    assert fixture.q.effective_registration(ACTOR, can_request=True) == effective
    assert fixture.service().effective_registration(ACTOR, can_request=True) == effective
    assert fixture.calls == ["config", "status", "permissions"]


def test_exact_replay_never_rechecks_provider_or_extends_and_conflict_is_fixed(fixture):
    request = fixture.request()
    first, _ = fixture.q.qualify(ACTOR, request, can_request=True)
    fixture.clock[0] += 100
    replay, status = fixture.service().qualify(ACTOR, request, can_request=True)
    assert status == 200 and replay["window"] == first["window"] and len(fixture.calls) == 3
    error("request_conflict", lambda: fixture.q.qualify(ACTOR, {**request, "policy_revision": "f" * 64}, can_request=True))
    error("qualification_busy", lambda: fixture.q.qualify(ACTOR, fixture.request("another-key"), can_request=True))
    assert len(fixture.calls) == 3


def test_other_actor_and_nonadmin_never_receive_dynamic_authority(fixture):
    first, _ = fixture.q.qualify(ACTOR, fixture.request(), can_request=True)
    other = fixture.q.inspect(OTHER, can_request=True)
    assert other["window"] is None and first["window"]["ref"] not in json.dumps(other)
    assert fixture.q.effective_registration(OTHER, can_request=True).allowed_actions == ("status",)
    assert fixture.q.effective_registration(ACTOR, can_request=False).allowed_actions == ("status",)
    assert fixture.q.inspect(ACTOR, can_request=False)["window"]["state"] == "retired"
    second, status = fixture.q.qualify(OTHER, fixture.request(), can_request=True)
    assert status == 201 and second["window"]["ref"] != first["window"]["ref"]
    assert second["window"]["registration_revision"] != first["window"]["registration_revision"]


def test_expired_base_diagnostic_and_grant_expiry_never_extend_or_mutate(fixture):
    fixture.clock[0] = NOW + 700
    assert fixture.q.inspect(ACTOR, can_request=True)["target"] is not None
    diagnostic = fixture.q.effective_registration(ACTOR, can_request=True)
    assert diagnostic.allowed_actions == ("status",) and diagnostic.expires_at == stamp(NOW + 7200)
    active, _ = fixture.q.qualify(ACTOR, fixture.request(), can_request=True)
    fixture.clock[0] += 901
    expired = fixture.q.inspect(ACTOR, can_request=True)
    assert expired["window"]["state"] == "expired"
    assert fixture.q.effective_registration(ACTOR, can_request=True).allowed_actions == ("status",)
    replay, status = fixture.q.qualify(ACTOR, fixture.request(), can_request=True)
    assert status == 200 and replay["window"]["expires_at"] == active["window"]["expires_at"]


def test_missing_policy_preserves_legacy_but_disabled_policy_strips_power(fixture):
    fixture.document["allowed_actions"] = ["status", "start", "shutdown"]
    fixture.manifest.write_text(json.dumps(fixture.document))
    fixture.policy.unlink()
    assert fixture.q.inspect(ACTOR, can_request=True)["policy"]["enabled"] is False
    assert fixture.q.effective_registration(ACTOR, can_request=False).allowed_actions == ("status", "start", "shutdown")
    fixture.policy_document.update(enabled=False, configuration_revision=fixture.base().revision)
    fixture.write_policy()
    assert fixture.q.effective_registration(ACTOR, can_request=True).allowed_actions == ("status",)
    error("policy_disabled", lambda: fixture.q.qualify(ACTOR, fixture.request(), can_request=True))


@pytest.mark.parametrize("field,value", [("schema", "wrong"), ("enabled", 1), ("window_seconds", True),
    ("window_seconds", 901), ("allowed_actions", ["start"]), ("configuration_revision", "f" * 64),
    ("registration_id", "wrong"), ("credential_expires_at", "invalid")])
def test_invalid_policy_fails_closed_without_manual_fallback(fixture, field, value):
    fixture.policy_document[field] = value
    fixture.write_policy()
    assert fixture.q.inspect(ACTOR, can_request=True)["policy"]["enabled"] is False
    error("invalid_policy", lambda: fixture.q.effective_registration(ACTOR, can_request=True))
    assert fixture.calls == []


@pytest.mark.parametrize("kind", ["duplicate", "unknown", "symlink", "permissions", "expired", "exact-bound"])
def test_policy_shape_trust_and_credential_end_bound(fixture, kind):
    code = "invalid_policy"
    if kind == "duplicate":
        fixture.policy.write_text(fixture.policy.read_text().replace('"enabled": true', '"enabled": true,"enabled": false'))
    elif kind == "unknown":
        fixture.policy_document["secret"] = "no"; fixture.write_policy()
    elif kind == "symlink":
        real = fixture.root / "retained-policy"; fixture.policy.rename(real); fixture.policy.symlink_to(real)
    elif kind == "permissions":
        fixture.policy.chmod(0o666)
    else:
        fixture.policy_document["credential_expires_at"] = stamp(NOW if kind == "expired" else NOW + 900)
        fixture.write_policy(); code = "policy_expired"
    request = {"target_ref": "1" * 32, "configuration_revision": fixture.base().revision,
               "policy_revision": hashlib.sha256(fixture.policy.read_bytes()).hexdigest(), "request_key": "fixture"}
    error(code, lambda: fixture.q.qualify(ACTOR, request, can_request=True))
    assert fixture.calls == []


@pytest.mark.parametrize("kind,code", [("name", "instance_changed"), ("uuid", "instance_changed"),
    ("lock", "state_mismatch"), ("state", "invalid_response"), ("permission_missing", "permissions_unavailable"),
    ("permission_false", "permissions_unavailable"), ("permission_wrong_path", "permissions_unavailable")])
def test_failed_native_get_evidence_rejects_original_request_without_power(fixture, kind, code):
    if kind in ("name", "uuid", "lock"):
        config = {"name": "fictional-guest", "smbios1": "uuid=" + fixture.document["instance_uuid"]}
        if kind == "name": config["name"] = "wrong"
        elif kind == "uuid": config["smbios1"] = "uuid=00000000-0000-0000-0000-000000000000"
        else: config["lock"] = "backup"
        fixture.hooks["config"] = lambda: config
    elif kind == "state": fixture.hooks["status"] = lambda: {"status": "unknown"}
    elif kind == "permission_missing": fixture.hooks["permissions"] = lambda: {"/vms/5000": {"VM.Audit": 0}}
    elif kind == "permission_false": fixture.hooks["permissions"] = lambda: {"/vms/5000": {"VM.Audit": False, "VM.PowerMgmt": 0}}
    else: fixture.hooks["permissions"] = lambda: {"/vms/5001": {"VM.Audit": 0, "VM.PowerMgmt": 0}}
    request = fixture.request()
    dto, status = fixture.q.qualify(ACTOR, request, can_request=True)
    assert status == 409 and dto["window"]["state"] == "rejected" and dto["window"]["error"] == code
    before = fixture.calls.copy()
    fixture.q.qualify(ACTOR, request, can_request=True)
    assert fixture.calls == before
    assert fixture.q.effective_registration(ACTOR, can_request=True).allowed_actions == ("status",)


def test_policy_and_config_replacement_retire_prior_grants(fixture):
    first, _ = fixture.q.qualify(ACTOR, fixture.request(), can_request=True)
    fixture.policy_document["credential_expires_at"] = stamp(NOW + 7300); fixture.write_policy()
    assert fixture.q.inspect(ACTOR, can_request=True)["window"]["state"] == "retired"
    assert fixture.q.effective_registration(ACTOR, can_request=True).allowed_actions == ("status",)
    fixture.document["name"] = "changed-config"; fixture.manifest.write_text(json.dumps(fixture.document))
    error("invalid_policy", lambda: fixture.q.effective_registration(ACTOR, can_request=True))


@pytest.mark.parametrize("change", ["policy", "base", "session", "deadline", "active_power"])
def test_changes_during_gets_prevent_final_publication(fixture, change):
    def mutate():
        if change == "policy":
            fixture.policy_document["credential_expires_at"] = stamp(NOW + 7300); fixture.write_policy()
        elif change == "base":
            fixture.document["name"] = "changed"; fixture.manifest.write_text(json.dumps(fixture.document))
        elif change == "session": fixture.current[0] = False
        elif change == "deadline": fixture.mono[0] += 11; fixture.clock[0] += 11
        else:
            LabPowerStore(fixture.cfg.data_dir).admit(OTHER, "power", fixture.base().revision,
                                                    fixture.target(), "start", "stopped")
        return {"/vms/5000": {"VM.Audit": 0, "VM.PowerMgmt": 0}}
    fixture.hooks["permissions"] = mutate
    if change == "session":
        error("session_retired", lambda: fixture.q.qualify(ACTOR, fixture.request(), can_request=True))
        fixture.current[0] = True
    else:
        dto, status = fixture.q.qualify(ACTOR, fixture.request(), can_request=True)
        assert status == 409 and dto["window"]["state"] != "active"
    with sqlite3.connect(fixture.root / "data/lab-power/operations.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM qualification_requests WHERE state='active'").fetchone()[0] == 0


def test_active_old_instance_blocks_qualification_and_preserves_original_power_schema(fixture):
    store = LabPowerStore(fixture.cfg.data_dir)
    row, _ = store.admit(OTHER, "power", fixture.base().revision, fixture.target().replace(
        fixture.document["instance_uuid"], "00000000-0000-0000-0000-000000000000"), "start", "stopped")
    with sqlite3.connect(store.path) as connection:
        schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='operations'").fetchone()[0]
    error("target_busy", lambda: fixture.q.qualify(ACTOR, fixture.request(), can_request=True))
    assert fixture.calls == [] and store.get(row["id"], OTHER) == row
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT sql FROM sqlite_master WHERE name='operations'").fetchone()[0] == schema


def test_memory_error_preserves_pending_and_restart_reaps_without_provider_retry(fixture):
    original = MemoryError("fictional allocation")
    fixture.hooks["config"] = Mock(side_effect=original)
    request = fixture.request()
    with pytest.raises(MemoryError) as caught:
        fixture.q.qualify(ACTOR, request, can_request=True)
    assert caught.value is original
    assert fixture.q.inspect(ACTOR, can_request=True)["window"]["state"] == "preparing"
    replay, status = fixture.service().qualify(ACTOR, request, can_request=True)
    assert status == 202 and len(fixture.calls) == 1
    fixture.clock[0] += 11
    fixture.mono[0] = 1.0
    reaped = fixture.service().inspect(ACTOR, can_request=True)
    assert reaped["window"]["state"] == "rejected" and reaped["window"]["error"] == "qualification_timeout"
    fixture.service().qualify(ACTOR, request, can_request=True)
    assert len(fixture.calls) == 1


def test_cas_prevents_late_completion_from_resurrecting_reaped_preparation(fixture):
    def retire():
        with sqlite3.connect(fixture.root / "data/lab-power/operations.sqlite3") as connection:
            connection.execute("UPDATE qualification_requests SET state='rejected',error='qualification_timeout',version=version+1 WHERE state='preparing'")
        return {"/vms/5000": {"VM.Audit": 0, "VM.PowerMgmt": 0}}
    fixture.hooks["permissions"] = retire
    dto, status = fixture.q.qualify(ACTOR, fixture.request(), can_request=True)
    assert status == 409 and dto["window"]["state"] == "rejected"
    assert fixture.q.effective_registration(ACTOR, can_request=True).allowed_actions == ("status",)


def test_unknown_store_state_and_wrong_table_fail_closed(fixture, monkeypatch):
    class Unavailable:
        def __init__(self, *_args): raise RuntimeError("PRIVATE path")
    with monkeypatch.context() as ports:
        ports.setattr(qualification, "LabPowerStore", Unavailable)
        dto = fixture.q.inspect(ACTOR, can_request=True)
        assert dto["busy"] is None and dto["can_request"] is False and dto["reason"] == "store_unavailable"
        error("store_unavailable", lambda: fixture.q.qualify(ACTOR, fixture.request(), can_request=True))
    store = LabPowerStore(fixture.cfg.data_dir)
    with sqlite3.connect(store.path) as connection:
        connection.execute("CREATE TABLE qualification_requests (id TEXT)")
    error("store_unavailable", lambda: fixture.q.qualify(ACTOR, fixture.request(), can_request=True))


@pytest.mark.parametrize("value", [False, None, 1, "yes"])
def test_admin_eligibility_is_original_server_boolean(fixture, value):
    error("role_required", lambda: fixture.q.qualify(ACTOR, fixture.request(), can_request=value))
    assert fixture.q.inspect(ACTOR, can_request=value)["can_request"] is False
    assert fixture.calls == []


@pytest.mark.parametrize("changes", [{"duration": "900"}, {"request_key": ""}, {"request_key": "x" * 129},
                                   {"request_key": "bad\nkey"}, {"policy_revision": "wrong"}, {"target_ref": True}])
def test_exact_request_validation_copies_and_rejects_extra_scope(fixture, changes):
    request = fixture.request(); request.update(changes)
    error("invalid_request", lambda: qualification.validate_request(request))
    original = fixture.request(); copied = qualification.validate_request(original)
    assert copied == original and copied is not original


def test_qualification_history_capacity_preserves_original_replay(fixture):
    fixture.hooks["permissions"] = lambda: {}
    request = fixture.request()
    original, status = fixture.q.qualify(ACTOR, request, can_request=True)
    assert status == 409
    with sqlite3.connect(fixture.root / "data/lab-power/operations.sqlite3") as connection:
        values = list(connection.execute("SELECT * FROM qualification_requests").fetchone())
        for index in range(1023):
            values[0], values[2] = f"{index:032x}", f"capacity-{index}"
            connection.execute("INSERT INTO qualification_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
    metadata = fixture.q.inspect(ACTOR, can_request=True)
    assert metadata["can_request"] is False and metadata["reason"] == "capacity_exceeded"
    error("capacity_exceeded", lambda: fixture.q.qualify(ACTOR, fixture.request("extra"), can_request=True))
    replay, status = fixture.q.qualify(ACTOR, request, can_request=True)
    assert status == 200 and replay["window"] == original["window"]
    assert fixture.calls == ["config", "status", "permissions"]


@pytest.mark.parametrize("committed", [False, True])
def test_lost_activation_commit_ack_recovers_without_repeating_provider_gets(fixture, monkeypatch, committed):
    connect = sqlite3.connect

    class CommitLoss(sqlite3.Connection):
        activating = False
        def execute(self, sql, *args):
            if sql.startswith("UPDATE qualification_requests SET state='active'"):
                self.activating = True
            if sql == "COMMIT" and self.activating:
                if committed:
                    super().execute(sql, *args)
                raise sqlite3.OperationalError("FICTIONAL PRIVATE ACK LOSS")
            return super().execute(sql, *args)

    def injected(*args, **kwargs):
        kwargs["factory"] = CommitLoss
        return connect(*args, **kwargs)

    request = fixture.request()
    with monkeypatch.context() as ports:
        ports.setattr(sqlite3, "connect", injected)
        error("store_unavailable", lambda: fixture.q.qualify(ACTOR, request, can_request=True))
    recovered = fixture.service().inspect(ACTOR, can_request=True)
    assert recovered["window"]["state"] == ("active" if committed else "preparing")
    replay, status = fixture.service().qualify(ACTOR, request, can_request=True)
    assert status == (200 if committed else 202)
    assert replay["window"] == recovered["window"]
    effective = fixture.service().effective_registration(ACTOR, can_request=True)
    assert effective.allowed_actions == (("status", "start", "shutdown") if committed else ("status",))
    assert fixture.calls == ["config", "status", "permissions"]


@pytest.mark.parametrize("fault", ["exception", "nan", "naive", "out_of_range", "memory"])
def test_post_activation_clock_failure_keeps_committed_grant_and_get_recovers(fixture, monkeypatch, fault):
    connect = sqlite3.connect
    activated = [False]
    original = MemoryError("FICTIONAL allocation failure")

    class ObserveCommit(sqlite3.Connection):
        activating = False
        def execute(self, sql, *args):
            if sql.startswith("UPDATE qualification_requests SET state='active'"):
                self.activating = True
            result = super().execute(sql, *args)
            if sql == "COMMIT" and self.activating:
                activated[0] = True
            return result

    def clock():
        if not activated[0]:
            return NOW
        if fault == "exception":
            raise RuntimeError("FICTIONAL private clock fault")
        if fault == "memory":
            raise original
        return {"nan": float("nan"), "naive": datetime.datetime(2026, 11, 13),
                "out_of_range": 2**53 - 1}[fault]

    def injected(*args, **kwargs):
        return connect(*args, **dict(kwargs, factory=ObserveCommit))

    request = fixture.request()
    fixture.q.clock = clock
    with monkeypatch.context() as ports:
        ports.setattr(sqlite3, "connect", injected)
        if fault == "memory":
            with pytest.raises(MemoryError) as caught:
                fixture.q.qualify(ACTOR, request, can_request=True)
            assert caught.value is original
        else:
            error("store_unavailable", lambda: fixture.q.qualify(ACTOR, request, can_request=True))
    assert activated[0] is True
    with connect(fixture.root / "data/lab-power/operations.sqlite3") as connection:
        row = connection.execute("SELECT id,effective_revision,qualified_at,expires_at,state FROM qualification_requests").fetchone()
    recovered = fixture.service().inspect(ACTOR, can_request=True)
    assert recovered["window"] == {"ref": row[0], "registration_revision": row[1],
            "qualified_at": stamp(row[2]), "expires_at": stamp(row[3]), "state": "active", "error": None}
    assert row[4] == "active"
    replay, status = fixture.service().qualify(ACTOR, request, can_request=True)
    assert status == 200 and replay["window"] == recovered["window"]
    assert fixture.calls == ["config", "status", "permissions"]


def test_bad_client_body_remains_invalid_request_before_admission(fixture):
    request = fixture.request(); request["duration"] = "900"
    error("invalid_request", lambda: fixture.q.qualify(ACTOR, request, can_request=True))
    assert fixture.calls == []
    assert not (fixture.root / "data/lab-power/operations.sqlite3").exists()


def test_timestamp_format_failure_is_unavailable_and_preserves_memory_error(monkeypatch):
    error("store_unavailable", lambda: qualification._stamp(2**53 - 1))
    original = MemoryError("FICTIONAL formatting allocation")
    class BrokenDate:
        @staticmethod
        def fromtimestamp(*_args):
            raise original
    monkeypatch.setattr(qualification.datetime, "datetime", BrokenDate)
    with pytest.raises(MemoryError) as caught:
        qualification._stamp(NOW)
    assert caught.value is original


def test_expired_grant_retains_exact_read_witness_and_busy_prevents_new_window(fixture):
    fixture.q.qualify(ACTOR, fixture.request(), can_request=True)
    granted = fixture.q.effective_registration(ACTOR, can_request=True)
    store = LabPowerStore(fixture.cfg.data_dir)
    store.admit(ACTOR, "held-power", granted.revision, fixture.target(), "start", "stopped")
    fixture.clock[0] += 900
    expired = fixture.service().effective_registration(ACTOR, can_request=True)
    assert expired == qualification.dataclasses.replace(granted, allowed_actions=("status",))
    metadata = fixture.service().inspect(ACTOR, can_request=True)
    assert metadata["window"]["state"] == "expired"
    assert metadata["busy"] is True and metadata["can_request"] is False and metadata["reason"] == "target_busy"
    error("target_busy", lambda: fixture.q.qualify(ACTOR, fixture.request("fresh-intent"), can_request=True))
    assert fixture.calls == ["config", "status", "permissions"]


def test_role_withdrawal_retains_only_own_original_read_witness(fixture):
    fixture.q.qualify(ACTOR, fixture.request(), can_request=True)
    granted = fixture.q.effective_registration(ACTOR, can_request=True)
    withdrawn = fixture.service().effective_registration(ACTOR, can_request=False)
    assert withdrawn == qualification.dataclasses.replace(granted, allowed_actions=("status",))
    assert fixture.q.inspect(ACTOR, can_request=False)["window"]["state"] == "retired"
    other = fixture.q.effective_registration(OTHER, can_request=False)
    assert other.allowed_actions == ("status",) and other.revision != granted.revision
    assert other.expires_at != granted.expires_at
    assert fixture.q.inspect(OTHER, can_request=False)["window"] is None
    error("role_required", lambda: fixture.q.qualify(ACTOR, fixture.request("no-role"), can_request=False))
    fixture.clock[0] += 901
    assert fixture.service().effective_registration(ACTOR, can_request=False) == withdrawn
    fixture.current[0] = False
    error("session_retired", lambda: fixture.q.effective_registration(ACTOR, can_request=False))


@pytest.mark.parametrize("change", ["policy", "base"])
def test_changed_owner_binding_retires_expired_read_witness(fixture, change):
    fixture.q.qualify(ACTOR, fixture.request(), can_request=True)
    granted = fixture.q.effective_registration(ACTOR, can_request=True)
    fixture.clock[0] += 901
    assert fixture.q.effective_registration(ACTOR, can_request=True).revision == granted.revision
    if change == "base":
        fixture.document["name"] = "replacement-config"
        fixture.manifest.write_text(json.dumps(fixture.document))
        fixture.policy_document["configuration_revision"] = fixture.base().revision
    else:
        fixture.policy_document["credential_expires_at"] = stamp(NOW + 7300)
    fixture.write_policy()
    diagnostic = fixture.q.effective_registration(ACTOR, can_request=True)
    assert diagnostic.allowed_actions == ("status",) and diagnostic.revision != granted.revision
    assert fixture.q.inspect(ACTOR, can_request=True)["window"]["state"] == "retired"
    assert fixture.calls == ["config", "status", "permissions"]


@pytest.mark.parametrize("path", ["metadata", "effective", "replay", "conflict"])
@pytest.mark.parametrize("change", ["disabled", "missing_policy", "invalid_policy", "expired_policy",
    "policy_hash", "missing_registration", "invalid_registration", "base_hash", "credentials_missing"])
def test_observed_owner_revocation_durably_retires_all_actors_despite_exact_restore(fixture, path, change):
    request = fixture.request()
    first, _ = fixture.q.qualify(ACTOR, request, can_request=True)
    second, _ = fixture.q.qualify(OTHER, request, can_request=True)
    policy, manifest = fixture.policy.read_bytes(), fixture.manifest.read_bytes()
    secret = fixture.root / "fictional-token"
    secret_raw = secret.read_bytes()
    if change == "disabled":
        fixture.policy_document["enabled"] = False; fixture.write_policy()
    elif change == "missing_policy": fixture.policy.unlink()
    elif change == "invalid_policy": fixture.policy.write_bytes(b"not valid JSON")
    elif change == "expired_policy": fixture.clock[0] = NOW + 7200
    elif change == "policy_hash":
        fixture.policy_document["credential_expires_at"] = stamp(NOW + 7300); fixture.write_policy()
    elif change == "missing_registration": fixture.manifest.unlink()
    elif change == "invalid_registration": fixture.manifest.write_bytes(b"not valid JSON")
    elif change == "base_hash":
        fixture.document["name"] = "replacement-config"; fixture.manifest.write_text(json.dumps(fixture.document))
        fixture.policy_document["configuration_revision"] = hashlib.sha256(fixture.manifest.read_bytes()).hexdigest()
        fixture.write_policy()
    else: secret.unlink()
    try:
        if path == "metadata": fixture.q.inspect(ACTOR, can_request=True)
        elif path == "effective": fixture.q.effective_registration(ACTOR, can_request=True)
        elif path == "conflict":
            error("request_conflict", lambda: fixture.q.qualify(ACTOR, {**request, "policy_revision": "f" * 64}, can_request=True))
        else: fixture.q.qualify(ACTOR, request, can_request=True)
    except qualification.QualificationError as failure:
        assert failure.code in {"invalid_policy", "policy_expired", "registration_unavailable", "credentials_unavailable"}
    fixture.policy.write_bytes(policy); fixture.policy.chmod(0o600)
    fixture.manifest.write_bytes(manifest); fixture.manifest.chmod(0o600)
    secret.write_bytes(secret_raw); secret.chmod(0o600)
    fixture.clock[0] = NOW
    for actor, old in ((ACTOR, first), (OTHER, second)):
        restored = fixture.service().inspect(actor, can_request=True)
        assert restored["window"]["state"] == "retired"
        assert restored["window"]["ref"] == old["window"]["ref"]
        assert restored["window"]["registration_revision"] == old["window"]["registration_revision"]
        diagnostic = fixture.service().effective_registration(actor, can_request=True)
        assert diagnostic.allowed_actions == ("status",)
        assert diagnostic.revision != old["window"]["registration_revision"]
        replay, status = fixture.service().qualify(actor, request, can_request=True)
        assert status == 200 and replay["window"] == restored["window"]
    with sqlite3.connect(fixture.root / "data/lab-power/operations.sqlite3") as connection:
        rows = connection.execute("SELECT state,version FROM qualification_requests").fetchall()
    assert rows == [("retired", 2), ("retired", 2)]
    assert fixture.calls == ["config", "status", "permissions"] * 2


def test_preparing_cas_cannot_activate_after_observed_revocation_and_exact_restore(fixture):
    policy = fixture.policy.read_bytes()
    def observe_and_restore():
        fixture.policy_document["enabled"] = False; fixture.write_policy()
        observed = fixture.service().inspect(OTHER, can_request=False)
        assert observed["window"] is None
        fixture.policy.write_bytes(policy)
        return {"/vms/5000": {"VM.Audit": 0, "VM.PowerMgmt": 0}}
    fixture.hooks["permissions"] = observe_and_restore
    request = fixture.request()
    dto, status = fixture.q.qualify(ACTOR, request, can_request=True)
    assert status == 409 and dto["window"]["state"] == "retired"
    assert dto["window"]["registration_revision"] is None and dto["window"]["qualified_at"] is None
    assert fixture.q.effective_registration(ACTOR, can_request=True).allowed_actions == ("status",)
    replay, status = fixture.q.qualify(ACTOR, request, can_request=True)
    assert status == 200 and replay["window"] == dto["window"]
    assert fixture.calls == ["config", "status", "permissions"]


def test_final_effective_context_observation_retires_before_refusal(fixture, monkeypatch):
    first, _ = fixture.q.qualify(ACTOR, fixture.request(), can_request=True)
    policy = fixture.policy.read_bytes()
    read = fixture.q._policy
    count = [0]
    def revoke_on_recheck(base, now):
        count[0] += 1
        if count[0] == 2:
            fixture.policy_document["enabled"] = False; fixture.write_policy()
        return read(base, now)
    monkeypatch.setattr(fixture.q, "_policy", revoke_on_recheck)
    error("policy_changed", lambda: fixture.q.effective_registration(ACTOR, can_request=True))
    fixture.policy.write_bytes(policy)
    assert fixture.service().inspect(ACTOR, can_request=True)["window"]["state"] == "retired"
    assert fixture.service().effective_registration(ACTOR, can_request=True).revision != first["window"]["registration_revision"]


def test_owner_restore_requires_new_explicit_qualification_not_replay(fixture):
    request = fixture.request()
    first, _ = fixture.q.qualify(ACTOR, request, can_request=True)
    policy = fixture.policy.read_bytes()
    fixture.policy.unlink()
    fixture.q.inspect(OTHER, can_request=True)
    fixture.policy.write_bytes(policy); fixture.policy.chmod(0o600)
    replay, status = fixture.q.qualify(ACTOR, request, can_request=True)
    assert status == 200 and replay["window"]["state"] == "retired"
    fresh, status = fixture.q.qualify(ACTOR, fixture.request("new-explicit-intent"), can_request=True)
    assert status == 201 and fresh["window"]["ref"] != first["window"]["ref"]
    assert fresh["window"]["registration_revision"] != first["window"]["registration_revision"]
    assert fixture.calls == ["config", "status", "permissions"] * 2


@pytest.mark.parametrize("change", ["disabled", "missing", "invalid", "base"])
def test_final_post_provider_observation_retires_pending_and_other_active_grant(fixture, change):
    first, _ = fixture.q.qualify(ACTOR, fixture.request(), can_request=True)
    policy, manifest = fixture.policy.read_bytes(), fixture.manifest.read_bytes()
    def revoke_after_reads():
        if change == "disabled":
            fixture.policy_document["enabled"] = False; fixture.write_policy()
        elif change == "missing": fixture.policy.unlink()
        elif change == "invalid": fixture.policy.write_bytes(b"invalid JSON")
        else:
            fixture.document["name"] = "changed-config"
            fixture.manifest.write_text(json.dumps(fixture.document))
        return {"/vms/5000": {"VM.Audit": 0, "VM.PowerMgmt": 0}}
    fixture.hooks["permissions"] = revoke_after_reads
    result, status = fixture.q.qualify(OTHER, fixture.request(), can_request=True)
    assert status == 409 and result["window"]["state"] == "retired"
    fixture.policy.write_bytes(policy); fixture.policy.chmod(0o600)
    fixture.manifest.write_bytes(manifest)
    restored = fixture.service().inspect(ACTOR, can_request=True)
    assert restored["window"]["state"] == "retired"
    assert restored["window"]["ref"] == first["window"]["ref"]
    assert fixture.q.effective_registration(ACTOR, can_request=True).allowed_actions == ("status",)
    assert fixture.q.effective_registration(OTHER, can_request=True).allowed_actions == ("status",)
    assert fixture.calls == ["config", "status", "permissions"] * 2
