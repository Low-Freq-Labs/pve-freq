"""Local durable-store controls only; no API, provider or real guest effects."""
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from freq.services import lab_power_store as power


ACTOR = "a" * 64
OTHER = "b" * 64
REVISION = "c" * 64
TARGET = json.dumps({"estate": "fixture", "provider": "pve", "node": "fixture-node",
                     "guest_type": "qemu", "vmid": 6101, "instance_uuid": "fixture-instance"},
                    sort_keys=True, separators=(",", ":"))


def admit(store, key="fixture-request", **overrides):
    values = {"actor": ACTOR, "request_key": key, "registration_revision": REVISION,
              "target": TARGET, "action": "start", "expected_state": "stopped"}
    values.update(overrides)
    return store.admit(**values)


def failure(code, call):
    with pytest.raises(power.StoreError) as caught:
        call()
    assert caught.value.code == code
    assert str(caught.value) == code


def test_first_admission_is_committed_before_permission_and_reopen_never_redispatches(tmp_path):
    store = power.LabPowerStore(tmp_path)
    row, allowed = admit(store)
    assert allowed is True
    assert row["phase"] == "dispatching" and row["active"] == 1 and row["version"] == 0
    assert len(row["id"]) == 32 and row["id"] != "fixture-request"
    with sqlite3.connect(store.path) as reader:
        assert reader.execute("SELECT phase,active,version FROM operations").fetchone() == ("dispatching", 1, 0)
    reopened = power.LabPowerStore(tmp_path)
    previous, allowed = admit(reopened)
    assert previous == row and allowed is False
    assert reopened.get(row["id"], ACTOR) == row
    assert os.stat(tmp_path / "lab-power").st_mode & 0o777 == 0o700
    assert os.stat(store.path).st_mode & 0o777 == 0o600


@pytest.mark.parametrize("overrides", [
    {"registration_revision": "d" * 64}, {"target": TARGET.replace("6101", "6102")},
    {"action": "shutdown"}, {"expected_state": "running"},
])
def test_same_actor_key_requires_exact_parameters(tmp_path, overrides):
    store = power.LabPowerStore(tmp_path)
    row, _ = admit(store)
    failure("request_conflict", lambda: admit(store, **overrides))
    assert store.get(row["id"], ACTOR)["version"] == 0


def test_single_active_target_applies_across_actors_and_requests(tmp_path):
    store = power.LabPowerStore(tmp_path)
    admit(store)
    failure("target_busy", lambda: admit(store, key="other-key"))
    failure("target_busy", lambda: admit(store, actor=OTHER))
    different, allowed = admit(store, key="other-target", target=TARGET.replace("6101", "6102"))
    assert allowed and different["target"] != TARGET


def test_uncertain_remains_active_after_reopen_and_cannot_be_retired(tmp_path):
    store = power.LabPowerStore(tmp_path)
    row, _ = admit(store)
    pending = store.update(row["id"], ACTOR, 0, phase="uncertain", error="dispatch_uncertain")
    assert pending["active"] == 1
    reopened = power.LabPowerStore(tmp_path)
    assert admit(reopened)[1] is False
    failure("target_busy", lambda: admit(reopened, key="new-request"))
    failure("invalid_transition", lambda: reopened.update(row["id"], ACTOR, 1, phase="succeeded"))
    failure("invalid_request", lambda: reopened.update(row["id"], ACTOR, 1, active=0))


@pytest.mark.parametrize("terminal", ["succeeded", "failed", "rejected"])
def test_terminal_phase_is_frozen_and_only_trusted_terminal_update_releases_target(tmp_path, terminal):
    store = power.LabPowerStore(tmp_path)
    row, _ = admit(store)
    if terminal != "rejected":
        row = store.update(row["id"], ACTOR, row["version"], phase="acknowledged", upid="UPID:fixture")
        row = store.update(row["id"], ACTOR, row["version"], phase="running", task_state="running")
    row = store.update(row["id"], ACTOR, row["version"], phase=terminal)
    assert row["active"] == 0
    assert admit(store)[1] is False
    failure("invalid_transition", lambda: store.update(row["id"], ACTOR, row["version"], observed_state="running"))
    assert admit(store, key="next-operation")[1] is True


def test_upid_is_once_only_and_versions_prevent_stale_updates_and_phase_regression(tmp_path):
    store = power.LabPowerStore(tmp_path)
    row, _ = admit(store)
    row = store.update(row["id"], ACTOR, 0, phase="acknowledged", upid="UPID:fixture")
    failure("stale_version", lambda: store.update(row["id"], ACTOR, 0, phase="running"))
    failure("upid_conflict", lambda: store.update(row["id"], ACTOR, 1, upid="UPID:different"))
    failure("upid_conflict", lambda: store.update(row["id"], ACTOR, 1, upid=None))
    failure("invalid_transition", lambda: store.update(row["id"], ACTOR, 1, phase="dispatching"))
    same = store.update(row["id"], ACTOR, 1, upid="UPID:fixture", observed_at=1234.5, observed_state="unknown")
    assert same["version"] == 2 and same["observed_at"] == 1234.5


def test_actor_cannot_read_or_update_another_operation(tmp_path):
    store = power.LabPowerStore(tmp_path)
    row, _ = admit(store)
    failure("not_found", lambda: store.get(row["id"], OTHER))
    failure("not_found", lambda: store.update(row["id"], OTHER, 0, phase="uncertain"))


@pytest.mark.parametrize("overrides", [
    {"actor": "caller"}, {"registration_revision": "not-a-hash"}, {"request_key": "x" * 129},
    {"request_key": "bad\nkey"}, {"action": "stop"}, {"action": "reset"},
    {"action": "reboot"}, {"expected_state": "unknown"}, {"target": "{} "},
    {"target": '[]'}, {"target": '{"x":1,"x":2}'}, {"target": '{"x":NaN}'},
])
def test_invalid_admission_never_grants_dispatch(tmp_path, overrides):
    store = power.LabPowerStore(tmp_path)
    failure("invalid_request", lambda: admit(store, **overrides))
    with sqlite3.connect(store.path) as reader:
        assert reader.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0


@pytest.mark.parametrize("fields", [
    {"token_secret": "private"}, {"target": "replacement"}, {"phase": []}, {"error": []},
    {"error": "raw private provider failure"}, {"task_exit": "raw task stderr"},
    {"observed_at": float("nan")}, {"observed_at": float("inf")},
    {"observed_at": 10 ** 1000}, {"upid": "bad\nUPID"}, {},
])
def test_unsafe_or_unknown_update_fields_leave_durable_row_unchanged(tmp_path, fields):
    store = power.LabPowerStore(tmp_path)
    row, _ = admit(store)
    failure("invalid_request", lambda: store.update(row["id"], ACTOR, 0, **fields))
    assert store.get(row["id"], ACTOR) == row


def test_row_quota_keeps_replay_but_refuses_new_operation(tmp_path):
    store = power.LabPowerStore(tmp_path)
    row, _ = admit(store)
    with sqlite3.connect(store.path) as connection:
        for index in range(1, power.MAX_ROWS):
            connection.execute("INSERT INTO operations SELECT ?,actor,?,registration_revision,?,?,action,expected_state,phase,active,upid,task_state,task_exit,observed_state,observed_at,error,version,created_at,updated_at FROM operations WHERE id=?",
                               (f"{index:032x}", str(index), f"fixture-target-{index}", f"fixture-slot-{index}", row["id"]))
    assert admit(store)[1] is False
    failure("capacity_exceeded", lambda: admit(store, key="over-quota", target=TARGET.replace("6101", "6102")))


def test_busy_sqlite_refuses_immediately_without_admission(tmp_path):
    store = power.LabPowerStore(tmp_path)
    with sqlite3.connect(store.path, isolation_level=None) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        failure("store_unavailable", lambda: admit(store))
        blocker.execute("ROLLBACK")
    assert admit(store)[1] is True


def test_sqlite_failure_cannot_grant_effect_permission(tmp_path, monkeypatch):
    store = power.LabPowerStore(tmp_path)
    effect = Mock()

    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("PRIVATE arbitrary SQL detail")

    monkeypatch.setattr(power.sqlite3, "connect", unavailable)
    with pytest.raises(power.StoreError, match="^store_unavailable$"):
        row, allowed = admit(store)
        if allowed:
            effect(row)
    effect.assert_not_called()


@pytest.mark.parametrize("committed", [False, True])
def test_commit_failure_never_returns_permission_and_uncertain_commit_cannot_redispatch(
        tmp_path, monkeypatch, committed):
    store = power.LabPowerStore(tmp_path)
    original_connect = sqlite3.connect

    class CommitFailure:
        def __init__(self, *args, **kwargs):
            object.__setattr__(self, "original", original_connect(*args, **kwargs))

        def __getattr__(self, name):
            return getattr(self.original, name)

        def __setattr__(self, name, value):
            setattr(self.original, name, value)

        def execute(self, sql, *args):
            if sql == "COMMIT":
                if committed:
                    self.original.execute(sql)
                raise sqlite3.OperationalError("PRIVATE commit acknowledgment unavailable")
            return self.original.execute(sql, *args)

    monkeypatch.setattr(power.sqlite3, "connect", CommitFailure)
    effect = Mock()
    with pytest.raises(power.StoreError, match="^store_unavailable$"):
        row, allowed = admit(store)
        if allowed:
            effect(row)
    effect.assert_not_called()
    monkeypatch.setattr(power.sqlite3, "connect", original_connect)
    row, allowed = admit(power.LabPowerStore(tmp_path))
    assert allowed is (not committed)
    assert row["active"] == 1


def test_concurrent_admission_cannot_grant_two_dispatches_for_one_target(tmp_path):
    store = power.LabPowerStore(tmp_path)

    def competing(key):
        try:
            return admit(store, key=key)[1]
        except power.StoreError as error:
            assert error.code in ("target_busy", "store_unavailable")
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(competing, ("first", "second"))).count(True) == 1


def test_request_key_punctuation_is_bound_as_sql_data(tmp_path):
    store = power.LabPowerStore(tmp_path)
    key = "request');DROP_TABLE_operations;--"
    row, allowed = admit(store, key=key)
    assert allowed and store.get(row["id"], ACTOR)["request_key"] == key
    assert admit(store, key=key)[1] is False


@pytest.mark.parametrize("kind", ["base-symlink", "directory-symlink", "file-symlink", "hardlink", "public-directory", "public-file", "fifo", "sidecar-symlink", "oversized"])
def test_unsafe_existing_paths_are_refused(tmp_path, kind):
    real = tmp_path / "real"
    real.mkdir()
    if kind == "base-symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(real, target_is_directory=True)
        failure("store_unavailable", lambda: power.LabPowerStore(alias))
        return
    store = power.LabPowerStore(real)
    directory, database = real / "lab-power", real / "lab-power" / "operations.sqlite3"
    if kind == "directory-symlink":
        directory.rename(real / "retained")
        directory.symlink_to(real / "retained", target_is_directory=True)
    elif kind in ("file-symlink", "hardlink", "fifo"):
        database.rename(directory / "retained")
        if kind == "file-symlink":
            database.symlink_to(directory / "retained")
        elif kind == "hardlink":
            os.link(directory / "retained", database)
        else:
            os.mkfifo(database, 0o600)
    elif kind == "public-directory":
        directory.chmod(0o755)
    elif kind == "public-file":
        database.chmod(0o644)
    elif kind == "sidecar-symlink":
        (directory / "operations.sqlite3-journal").symlink_to(database)
    else:
        with database.open("r+b") as stream:
            stream.truncate(power.MAX_DATABASE + 1)
    failure("capacity_exceeded" if kind == "oversized" else "store_unavailable", lambda: admit(store))


@pytest.mark.parametrize("phase", ["dispatching", "uncertain"])
def test_pending_old_instance_blocks_replacement_uuid_in_same_logical_slot(tmp_path, phase):
    store = power.LabPowerStore(tmp_path)
    row, _ = admit(store)
    if phase == "uncertain":
        row = store.update(row["id"], ACTOR, 0, phase=phase, error="dispatch_uncertain")
    replacement = TARGET.replace("fixture-instance", "replacement-instance")
    reopened = power.LabPowerStore(tmp_path)
    failure("target_busy", lambda: admit(reopened, key="replacement", target=replacement))
    failure("target_busy", lambda: admit(reopened, actor=OTHER, target=replacement))
    failure("request_conflict", lambda: admit(reopened, target=replacement))
    assert reopened.active_for_target(replacement) == row
    assert row["target"] == TARGET
    assert "instance_uuid" not in json.loads(row["target_slot"])
    assert json.loads(row["target_slot"]) == {
        key: value for key, value in json.loads(TARGET).items() if key != "instance_uuid"
    }


@pytest.mark.parametrize("field,value", [("estate", "another-estate"), ("provider", "another-provider"),
                                         ("node", "another-node"), ("guest_type", "lxc"), ("vmid", 6102)])
def test_busy_lookup_and_exclusion_do_not_cross_logical_slots(tmp_path, field, value):
    store = power.LabPowerStore(tmp_path)
    original, _ = admit(store)
    other = json.loads(TARGET)
    other[field] = value
    other = json.dumps(other, sort_keys=True, separators=(",", ":"))
    assert store.active_for_target(other) is None
    row, allowed = admit(store, key="other-slot", target=other)
    assert allowed is True
    assert store.active_for_target(other) == row
    assert store.active_for_target(TARGET) == original


def test_terminal_slot_release_and_session_retired_fixed_error(tmp_path):
    store = power.LabPowerStore(tmp_path)
    assert store.active_for_target(TARGET) is None
    row, _ = admit(store)
    failure("invalid_request", lambda: store.update(row["id"], ACTOR, 0, target_slot="changed"))
    row = store.update(row["id"], ACTOR, 0, phase="rejected", error="session_retired")
    assert row["active"] == 0 and row["error"] == "session_retired"
    assert store.active_for_target(TARGET) is None
    replacement = TARGET.replace("fixture-instance", "replacement-instance")
    new, allowed = admit(store, key="replacement", target=replacement)
    assert allowed and store.active_for_target(TARGET) == new


def test_previous_unreleased_schema_is_refused_without_migration_or_data_loss(tmp_path):
    directory = tmp_path / "lab-power"
    directory.mkdir(mode=0o700)
    database = directory / "operations.sqlite3"
    database.touch(mode=0o600)
    old_schema = power._SCHEMA.replace("target_slot TEXT NOT NULL, ", "")
    with sqlite3.connect(database) as connection:
        connection.execute(old_schema)
        connection.execute("CREATE UNIQUE INDEX active_target ON operations(target) WHERE active=1")
        connection.execute("INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           ("f" * 32, ACTOR, "old-request", REVISION, TARGET, "start", "stopped",
                            "uncertain", 1, None, None, None, None, None, None, 0, 1234.0, 1234.0))
    before = database.read_bytes()
    failure("store_unavailable", lambda: power.LabPowerStore(tmp_path))
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert "target_slot" not in [row[1] for row in connection.execute("PRAGMA table_info(operations)")]
        assert connection.execute("SELECT phase,active FROM operations").fetchone() == ("uncertain", 1)
