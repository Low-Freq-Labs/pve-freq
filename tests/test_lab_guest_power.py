"""Fake provider/session ports, real temp manifest and SQLite; no native effects.

The CA reader is a fictional port: these checks do not qualify certificates,
transport, HTTP authentication, a current lab registration or any real guest.
"""

import datetime
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from freq.services import lab_guest_power as power
from freq.services import lab_guest_registration as registrations
from freq.services.lab_power_store import LabPowerStore, StoreError
from freq.services.lab_pve_transport import LabPveTransport, LabTransportError


ACTOR = "a" * 64
OTHER = "b" * 64
NOW = datetime.datetime(2026, 11, 13, 12, tzinfo=datetime.timezone.utc).timestamp()


class FakeProvider:
    def __init__(self, case):
        self.case = case
        self.config = {"name": "fictional-guest", "smbios1": "uuid=12345678-1234-5678-9123-123456789abc"}
        self.status = {"status": "stopped"}
        self.action = "start"
        self.calls = []
        self.hooks = {}
        self.task_state = "running"
        self.task_exit = None

    def upid(self, action=None):
        kind = "qmstart" if (action or self.action) == "start" else "qmshutdown"
        return "UPID:fictional-pve:00000001:00000002:00000003:" + kind + ":5000:fixture@pve!power:"

    def _run(self, method, default, *args):
        self.calls.append((method, args))
        # Acquiring a second write transaction during every fake I/O proves the
        # orchestrator does not hold its admission/update transaction across I/O.
        path = Path(self.case.cfg.data_dir) / "lab-power" / "operations.sqlite3"
        if path.exists():
            with closing(sqlite3.connect(path, timeout=0, isolation_level=None)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                if method == "submit":
                    row = connection.execute("SELECT phase,active FROM operations WHERE active=1").fetchone()
                    self.case.assertEqual(row, ("dispatching", 1))
                connection.execute("ROLLBACK")
        hook = self.hooks.get(method)
        return hook(*args) if hook is not None else default

    def get_config(self):
        return self._run("config", self.config.copy())

    def get_status(self):
        return self._run("status", self.status.copy())

    def submit(self, action):
        self.action = action
        return self._run("submit", self.upid(), action)

    def get_task(self, upid):
        document = {"upid": self.upid(), "node": "fictional-pve", "id": "5000",
                    "user": "fixture@pve", "tokenid": "power",
                    "type": "qmstart" if self.action == "start" else "qmshutdown",
                    "status": self.task_state}
        if self.task_exit is not None:
            document["exitstatus"] = self.task_exit
        return self._run("task", document, upid)


def failing(error):
    def fail(*_args):
        raise error
    return fail


class RegisteredLabPowerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "conf").mkdir()
        (self.root / "data").mkdir()
        self.cfg = SimpleNamespace(conf_dir=str(self.root / "conf"), data_dir=str(self.root / "data"))
        secret = self.root / "fixture-token"
        secret.write_text("FICTIONAL-TOKEN\n")
        secret.chmod(0o600)
        self.document = {
            "schema": "pve-freq-lab-guest-v1", "registration_id": "11111111222233334444555555555555",
            "qualified_at": "2026-11-13T00:00:00Z", "expires_at": "2026-11-14T00:00:00Z",
            "lab_only": True, "estate": "fictional-estate", "provider": "pve.example.invalid",
            "node": "fictional-pve", "guest_type": "qemu", "vmid": 5000, "name": "fictional-guest",
            "instance_uuid": "12345678-1234-5678-9123-123456789abc",
            "allowed_actions": ["status", "start", "shutdown"],
            "credentials": {"token_id": "fixture@pve!power", "token_secret_file": str(secret),
                            "ca_file": str(self.root / "fictional-ca")},
            "qualification_ref": "fictional-evidence",
        }
        self.write_manifest()
        self.addCleanup(patch.stopall)
        patch.object(registrations, "read_ca", return_value=b"FICTIONAL-CA").start()
        patch.object(LabPveTransport, "_native", side_effect=AssertionError("native provider forbidden")).start()
        patch("socket.create_connection", side_effect=AssertionError("network forbidden")).start()
        self.provider = FakeProvider(self)
        self.factories = []
        self.current = True
        self.service = self.make_service()

    def write_manifest(self):
        path = self.root / "conf" / "lab-guest.json"
        path.write_text(json.dumps(self.document))
        path.chmod(0o600)

    def make_service(self, **kwargs):
        def transport(registration):
            self.factories.append(registration)
            return self.provider
        return power.RegisteredLabPower(self.cfg, transport_factory=transport,
                                        clock=lambda: NOW, still_current=lambda: self.current, **kwargs)

    def request(self, **overrides):
        registration = registrations.load_registration(self.cfg, now=NOW)
        value = {"target_ref": registration.registration_id, "registration_revision": registration.revision,
                 "action": "start", "expected_state": "stopped", "request_key": "fictional-request"}
        value.update(overrides)
        return value

    def submit(self, **kwargs):
        return self.service.submit(ACTOR, self.request(**kwargs))

    def store(self):
        return LabPowerStore(self.cfg.data_dir)

    def poll(self, row):
        return self.service.poll(ACTOR, row["id"])

    def assert_error(self, code, call):
        with self.assertRaises(power.LabPowerError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code)

    def assert_no_submission(self):
        self.assertFalse(any(method == "submit" for method, _ in self.provider.calls))

    def test_inspect_returns_actual_scoped_state_without_private_material(self):
        result = self.service.inspect(ACTOR)
        self.assertEqual(result["observed_state"], "stopped")
        self.assertEqual(result["observed_at"], NOW)
        self.assertFalse(result["busy"])
        self.assertIsNone(result["operation"])
        self.assertEqual(result["capability_scope"]["allowed_actions"], ["status", "start", "shutdown"])
        public = json.dumps(result)
        for private in ("FICTIONAL-TOKEN", "fixture@pve!power", str(self.root)):
            self.assertNotIn(private, public)
        self.assert_no_submission()

    def test_busy_inspection_hides_other_actor_operation_and_exposes_own_summary(self):
        row = self.submit()
        own = self.service.inspect(ACTOR)
        self.assertEqual(own["operation"]["id"], row["id"])
        self.assertNotIn("upid", own["operation"])
        other = self.service.inspect(OTHER)
        self.assertTrue(other["busy"])
        self.assertIsNone(other["operation"])
        self.assertNotIn(row["id"], json.dumps(other))
        self.assertNotIn(ACTOR, json.dumps(other))

    def test_bad_actor_exact_schema_and_input_types_refuse_before_provider(self):
        good = self.request()
        for actor in (None, "caller", "A" * 64, True):
            with self.subTest(actor=actor):
                self.assert_error("invalid_request", lambda: self.service.submit(actor, good))
        invalid = [None, [], {**good, "node": "arbitrary"}, {k: v for k, v in good.items() if k != "request_key"}]
        invalid.extend({**good, field: value} for field, value in (
            ("action", "stop"), ("action", "reset"), ("action", True), ("expected_state", "unknown"),
            ("request_key", ""), ("request_key", "bad\nkey"), ("request_key", "x" * 129)))
        for request in invalid:
            with self.subTest(request=request):
                self.assert_error("invalid_request", lambda: self.service.submit(ACTOR, request))
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.factories, [])

    def test_wrong_reference_revision_or_ungranted_action_never_dispatches(self):
        for override in ({"target_ref": "wrong"}, {"registration_revision": "b" * 64}):
            self.assert_error("registration_changed", lambda: self.service.submit(ACTOR, self.request(**override)))
        self.document["allowed_actions"] = ["status"]
        self.write_manifest()
        self.assert_error("dispatch_rejected", self.submit)
        self.assertEqual(self.provider.calls, [])

    def test_expired_manifest_never_admits_or_calls_provider(self):
        self.document["expires_at"] = "2026-11-13T11:00:00Z"
        self.write_manifest()
        self.assert_error("registration_expired", lambda: self.service.submit(ACTOR, {} | {
            "target_ref": self.document["registration_id"], "registration_revision": "b" * 64,
            "action": "start", "expected_state": "stopped", "request_key": "fixture"}))
        self.assertEqual(self.provider.calls, [])

    def test_config_identity_failures_are_rejected_before_effect(self):
        original = self.provider.config.copy()
        for index, config in enumerate(({}, {"name": "other", "smbios1": original["smbios1"]},
                {**original, "smbios1": "uuid=00000000-0000-0000-0000-000000000000"},
                {**original, "smbios1": original["smbios1"] + ",UUID=12345678-1234-5678-9123-123456789abc"},
                {**original, "node": "another-pve"}, {**original, "vmid": 5001})):
            with self.subTest(config=config):
                self.provider.config = config
                row = self.submit(request_key="identity-" + str(index))
                self.assertEqual((row["phase"], row["error"], row["active"]), ("rejected", "instance_changed", 0))
        self.assert_no_submission()

    def test_unknown_or_wrong_expected_state_is_rejected_before_effect(self):
        for index, state in enumerate((None, True, "paused", "running")):
            with self.subTest(state=state):
                self.provider.status["status"] = state
                row = self.submit(request_key="state-" + str(index))
                self.assertEqual(row["phase"], "rejected")
                self.assertEqual(row["error"], "state_mismatch" if state == "running" else "invalid_response")
        self.assert_no_submission()

    def test_manifest_replaced_or_expired_during_preflight_rejects_without_post(self):
        for index, expires in enumerate((False, True)):
            self.document["expires_at"] = "2026-11-14T00:00:00Z"
            self.write_manifest()
            def change():
                self.document["expires_at"] = "2026-11-13T11:00:00Z" if expires else "2026-11-15T00:00:00Z"
                self.write_manifest()
                return self.provider.status.copy()
            self.provider.hooks["status"] = change
            row = self.submit(request_key="manifest-" + str(index))
            self.assertEqual((row["phase"], row["error"]), ("rejected", "registration_changed"))
        self.assert_no_submission()

    def test_retired_session_before_and_during_preflight_cannot_dispatch(self):
        self.current = False
        self.assert_error("session_retired", self.submit)
        self.current = True
        def retire():
            self.current = False
            return self.provider.status.copy()
        self.provider.hooks["status"] = retire
        row = self.submit()
        self.assertEqual((row["phase"], row["error"]), ("rejected", "session_retired"))
        self.assert_no_submission()

    def test_only_literal_true_session_callback_is_current(self):
        for value in (1, "yes", None):
            self.service.still_current = lambda: value
            self.assert_error("session_retired", self.submit)
        self.service.still_current = failing(RuntimeError("PRIVATE callback"))
        self.assert_error("session_retired", self.submit)
        self.assert_no_submission()

    def test_acknowledgement_is_not_success_and_replay_survives_service_restart(self):
        request = self.request()
        row = self.service.submit(ACTOR, request)
        self.assertEqual((row["phase"], row["active"], row["observed_state"]), ("acknowledged", 1, "stopped"))
        self.assertIsNone(row["task_exit"])
        self.assertEqual(json.loads(row["target"]), {key: self.document[key] for key in (
            "estate", "provider", "node", "guest_type", "vmid", "instance_uuid")})
        before = list(self.provider.calls)
        self.assertEqual(self.make_service().submit(ACTOR, request), row)
        self.assertEqual(self.provider.calls, before)

    def test_request_draft_mutation_during_io_cannot_change_admitted_action(self):
        request = self.request()
        def edit():
            request["action"] = "shutdown"
            return self.provider.config.copy()
        self.provider.hooks["config"] = edit
        row = self.service.submit(ACTOR, request)
        self.assertEqual(row["action"], "start")
        self.assertIn(("submit", ("start",)), self.provider.calls)

    def test_replay_conflict_and_busy_never_make_a_second_effect(self):
        request = self.request()
        self.service.submit(ACTOR, request)
        before = list(self.provider.calls)
        self.assert_error("request_conflict", lambda: self.service.submit(ACTOR, {
            **request, "action": "shutdown", "expected_state": "running"}))
        self.assert_error("target_busy", lambda: self.submit(request_key="different-key"))
        self.assert_error("target_busy", lambda: self.service.submit(OTHER, request))
        self.assertEqual(self.provider.calls, before)

    def test_pre_attempt_failure_rejects_but_post_attempt_failure_stays_uncertain(self):
        for index, uncertain in enumerate((False, True)):
            self.provider.hooks["submit"] = failing(LabTransportError("tls_unavailable", uncertain=uncertain))
            row = self.submit(request_key="transport-" + str(index))
            self.assertEqual(row["phase"], "uncertain" if uncertain else "rejected")
            self.assertEqual(row["error"], "dispatch_uncertain" if uncertain else "tls_unavailable")
        before = list(self.provider.calls)
        self.assertEqual(self.make_service().submit(ACTOR, self.request(request_key="transport-1")), row)
        self.assertEqual(self.poll(row), row)
        self.assertEqual(self.provider.calls, before)

    def test_generic_post_exception_has_uncertain_effect_without_raw_message(self):
        self.provider.hooks["submit"] = failing(RuntimeError("PRIVATE token path stderr"))
        row = self.submit()
        self.assertEqual((row["phase"], row["error"]), ("uncertain", "dispatch_uncertain"))
        self.assertNotIn("PRIVATE", json.dumps(row))
        self.assert_error("target_busy", lambda: self.submit(request_key="not-a-retry"))

    def test_malformed_or_wrong_scope_upid_is_never_accepted_or_retried(self):
        base = self.provider.upid()
        for index, upid in enumerate((None, True, "UPID:bad", base.replace("fictional-pve", "other-pve"),
                base.replace(":5000:", ":5001:"), base.replace("qmstart", "qmshutdown"),
                base.replace("fixture@pve!power", "other@pve!power"))):
            with self.subTest(upid=upid):
                # Each uncertain case requires a genuinely different fictional target.
                directory = self.root / ("case-" + str(index))
                directory.mkdir()
                self.cfg.data_dir = str(directory)
                self.provider.hooks["submit"] = lambda _action: upid
                row = self.submit()
                self.assertEqual((row["phase"], row["upid"]), ("uncertain", None))
                before = list(self.provider.calls)
                self.assertEqual(self.poll(row), row)
                self.assertEqual(self.provider.calls, before)

    def test_memory_error_before_and_after_post_propagates_and_retains_pending(self):
        for index, method in enumerate(("config", "submit")):
            directory = self.root / ("oom-" + str(index))
            directory.mkdir()
            self.cfg.data_dir = str(directory)
            self.provider.hooks.clear()
            original = MemoryError("fictional allocation failure")
            self.provider.hooks[method] = failing(original)
            request = self.request()
            with self.assertRaises(MemoryError) as caught:
                self.service.submit(ACTOR, request)
            self.assertIs(caught.exception, original)
            before = list(self.provider.calls)
            row = self.make_service().submit(ACTOR, request)
            self.assertEqual((row["phase"], row["active"], row["upid"]), ("dispatching", 1, None))
            self.assertEqual(self.provider.calls, before)

    def test_admission_failure_has_no_provider_io_and_no_effect_grant(self):
        class UnavailableStore:
            def __init__(self, _directory):
                pass
            admit = failing(StoreError("store_unavailable"))
        self.service = self.make_service(store_factory=UnavailableStore)
        self.assert_error("store_unavailable", self.submit)
        self.assertEqual(self.provider.calls, [])

    def test_ack_persistence_loss_never_resubmits_after_restart(self):
        class FailingAckStore(LabPowerStore):
            def update(self, *_args, **_kwargs):
                raise StoreError("store_unavailable")
        self.service = self.make_service(store_factory=FailingAckStore)
        request = self.request()
        self.assert_error("store_unavailable", lambda: self.service.submit(ACTOR, request))
        before = list(self.provider.calls)
        row = self.make_service().submit(ACTOR, request)
        self.assertEqual(row["phase"], "dispatching")
        self.assertEqual(self.provider.calls, before)

    def test_committed_admission_with_lost_return_never_dispatches_on_reopen(self):
        class LostAdmissionReturn(LabPowerStore):
            def admit(self, *args):
                super().admit(*args)
                raise StoreError("store_unavailable")
        request = self.request()
        self.service = self.make_service(store_factory=LostAdmissionReturn)
        self.assert_error("store_unavailable", lambda: self.service.submit(ACTOR, request))
        self.assertEqual(self.provider.calls, [])
        row = self.make_service().submit(ACTOR, request)
        self.assertEqual((row["phase"], row["active"]), ("dispatching", 1))
        self.assertEqual(self.provider.calls, [])

    def test_ack_persistence_memory_error_preserves_original_and_pending_intent(self):
        original = MemoryError("fictional ack persistence failure")
        class FailedAckAllocation(LabPowerStore):
            def update(self, *_args, **_kwargs):
                raise original
        request = self.request()
        self.service = self.make_service(store_factory=FailedAckAllocation)
        with self.assertRaises(MemoryError) as caught:
            self.service.submit(ACTOR, request)
        self.assertIs(caught.exception, original)
        before = list(self.provider.calls)
        row = self.make_service().submit(ACTOR, request)
        self.assertEqual((row["phase"], row["upid"]), ("dispatching", None))
        self.assertEqual(self.provider.calls, before)

    def test_running_task_and_observed_state_remain_separate(self):
        row = self.poll(self.submit())
        self.assertEqual((row["phase"], row["task_state"], row["observed_state"]), ("running", "running", "stopped"))
        self.assertEqual([args for method, args in self.provider.calls if method == "task"], [(row["upid"],)])

    def test_task_ok_wrong_state_waits_then_same_upid_can_succeed(self):
        row = self.submit()
        self.provider.task_state, self.provider.task_exit = "stopped", "OK"
        pending = self.poll(row)
        self.assertEqual((pending["phase"], pending["task_exit"], pending["error"]),
                         ("acknowledged", "OK", "state_mismatch"))
        self.assertEqual(pending["active"], 1)
        self.provider.status["status"] = "running"
        result = self.poll(pending)
        self.assertEqual((result["phase"], result["active"], result["observed_state"]), ("succeeded", 0, "running"))

    def test_failed_task_retains_actual_observation_and_sanitizes_exit_detail(self):
        row = self.submit()
        self.provider.task_state, self.provider.task_exit = "stopped", "PRIVATE provider exit stderr"
        result = self.poll(row)
        self.assertEqual((result["phase"], result["task_exit"], result["observed_state"]), ("failed", "failed", "stopped"))
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_terminal_task_fact_survives_status_failure_and_later_task_get_loss(self):
        for index, task_exit in enumerate(("OK", "fictional failure")):
            with self.subTest(task_exit=task_exit):
                directory = self.root / ("terminal-" + str(index))
                directory.mkdir()
                self.cfg.data_dir = str(directory)
                self.provider.hooks.clear()
                row = self.submit()
                self.provider.task_state, self.provider.task_exit = "stopped", task_exit
                self.provider.hooks["status"] = failing(LabTransportError("provider_unavailable"))
                pending = self.poll(row)
                self.assertEqual(pending["phase"], "acknowledged")
                self.assertEqual(pending["task_state"], "stopped")
                self.assertEqual(pending["observed_state"], "unknown")
                self.provider.hooks.pop("status")
                self.provider.status["status"] = "running"
                self.provider.hooks["task"] = failing(LabTransportError("provider_unavailable"))
                result = self.poll(pending)
                self.assertEqual(result["phase"], "succeeded" if task_exit == "OK" else "failed")
                self.provider.status["status"] = "stopped"

    def test_transient_config_task_or_status_loss_is_recoverable_without_post_retry(self):
        for index, method in enumerate(("config", "task", "status")):
            with self.subTest(method=method):
                directory = self.root / ("transient-" + str(index))
                directory.mkdir()
                self.cfg.data_dir = str(directory)
                self.provider.hooks.clear()
                row = self.submit()
                self.provider.hooks[method] = failing(LabTransportError("provider_unavailable"))
                pending = self.poll(row)
                self.assertIn(pending["phase"], ("acknowledged", "running"))
                self.assertEqual(pending["error"], "observation_unavailable")
                self.provider.hooks.pop(method)
                self.provider.task_state, self.provider.task_exit = "stopped", "OK"
                self.provider.status["status"] = "running"
                result = self.poll(pending)
                self.assertEqual(result["phase"], "succeeded")
                self.provider.task_state, self.provider.task_exit = "running", None
                self.provider.status["status"] = "stopped"
        self.assertEqual(len([1 for method, _ in self.provider.calls if method == "submit"]), 3)

    def test_explicit_task_binding_contradiction_stays_uncertain(self):
        row = self.submit()
        def wrong_task(_upid):
            return {"upid": row["upid"], "node": "other-pve", "id": "5000", "user": "fixture@pve!power",
                    "type": "qmstart", "status": "stopped", "exitstatus": "OK"}
        self.provider.hooks["task"] = wrong_task
        pending = self.poll(row)
        self.assertEqual(pending["phase"], "uncertain")
        self.provider.hooks.pop("task")
        self.provider.task_state, self.provider.task_exit = "stopped", "OK"
        self.provider.status["status"] = "running"
        self.assertEqual(self.poll(pending)["phase"], "uncertain")

    def test_malformed_task_response_is_observation_loss_not_a_new_dispatch(self):
        row = self.submit()
        self.provider.hooks["task"] = lambda _upid: {"status": "stopped", "exitstatus": "OK"}
        pending = self.poll(row)
        self.assertEqual(pending["phase"], "acknowledged")
        self.assertEqual(pending["error"], "observation_unavailable")
        self.provider.hooks.pop("task")
        self.assertEqual(self.poll(pending)["phase"], "running")

    def test_task_terminal_fact_cannot_regress_to_running(self):
        row = self.submit()
        self.provider.task_state, self.provider.task_exit = "stopped", "OK"
        pending = self.poll(row)
        self.provider.task_state, self.provider.task_exit = "running", None
        result = self.poll(pending)
        self.assertEqual((result["phase"], result["task_state"], result["task_exit"]), ("uncertain", "stopped", "OK"))

    def test_registration_or_instance_change_during_poll_cannot_complete(self):
        row = self.submit()
        self.document["expires_at"] = "2026-11-15T00:00:00Z"
        self.write_manifest()
        before = list(self.provider.calls)
        result = self.poll(row)
        self.assertEqual((result["phase"], result["error"]), ("uncertain", "registration_changed"))
        self.assertEqual((result["observed_state"], result["observed_at"]), ("unknown", None))
        self.assertEqual(self.provider.calls, before)

    def test_manifest_changed_after_task_read_cannot_publish_success(self):
        row = self.submit()
        self.provider.task_state, self.provider.task_exit = "stopped", "OK"
        def replace():
            self.document["expires_at"] = "2026-11-15T00:00:00Z"
            self.write_manifest()
            return {"status": "running"}
        self.provider.hooks["status"] = replace
        result = self.poll(row)
        self.assertEqual((result["phase"], result["error"]), ("uncertain", "registration_changed"))
        self.assertEqual((result["observed_state"], result["observed_at"]), ("unknown", None))
        self.assertEqual(result["task_exit"], "OK")

    def test_uuid_changed_during_poll_cannot_complete(self):
        row = self.submit()
        self.provider.config["smbios1"] = "uuid=00000000-0000-0000-0000-000000000000"
        result = self.poll(row)
        self.assertEqual((result["phase"], result["error"]), ("uncertain", "instance_changed"))
        self.assertEqual(self.provider.calls[-1][0], "config")

    def test_session_retired_during_poll_keeps_uncertain_original_operation(self):
        row = self.submit()
        def retire():
            self.current = False
            return {"status": "running"}
        self.provider.hooks["status"] = retire
        self.provider.task_state, self.provider.task_exit = "stopped", "OK"
        result = self.poll(row)
        self.assertEqual((result["phase"], result["error"]), ("uncertain", "session_retired"))

    def test_terminal_history_never_loads_registration_or_reads_provider_again(self):
        row = self.submit()
        self.provider.task_state, self.provider.task_exit = "stopped", "OK"
        self.provider.status["status"] = "running"
        terminal = self.poll(row)
        (self.root / "conf" / "lab-guest.json").unlink()
        before = list(self.provider.calls)
        self.assertEqual(self.make_service().poll(ACTOR, row["id"]), terminal)
        self.assertEqual(self.provider.calls, before)

    def test_another_actor_cannot_poll_operation(self):
        row = self.submit()
        before = list(self.provider.calls)
        self.assert_error("not_found", lambda: self.service.poll(OTHER, row["id"]))
        self.assertEqual(self.provider.calls, before)

    def test_cas_stale_poll_returns_store_current_without_regression(self):
        row = self.submit()
        class RacingStore(LabPowerStore):
            def update(self, operation_id, actor, version, **fields):
                super().update(operation_id, actor, version, phase="succeeded", task_state="stopped",
                               task_exit="OK", observed_state="running", observed_at=NOW)
                return super().update(operation_id, actor, version, **fields)
        self.service = self.make_service(store_factory=RacingStore)
        current = self.poll(row)
        self.assertEqual((current["phase"], current["observed_state"], current["version"]), ("succeeded", "running", 2))

    def test_replacement_instance_stays_busy_under_original_logical_slot(self):
        self.provider.hooks["submit"] = failing(LabTransportError("provider_unavailable", uncertain=True))
        row = self.submit()
        self.document["instance_uuid"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        self.write_manifest()
        self.provider.config["smbios1"] = "uuid=" + self.document["instance_uuid"]
        self.assertTrue(self.service.inspect(OTHER)["busy"])
        self.assert_error("target_busy", lambda: self.submit(request_key="replacement"))
        self.assertEqual(self.store().get(row["id"], ACTOR)["active"], 1)

    def test_explicit_shutdown_cycle_uses_new_request_and_no_automatic_followup(self):
        self.provider.status["status"] = "running"
        row = self.submit(action="shutdown", expected_state="running")
        self.assertEqual(row["phase"], "acknowledged")
        self.provider.task_state, self.provider.task_exit = "stopped", "OK"
        self.provider.status["status"] = "stopped"
        self.assertEqual(self.poll(row)["phase"], "succeeded")
        self.assertEqual([args for method, args in self.provider.calls if method == "submit"], [("shutdown",)])
        start = self.submit(request_key="separate-start", action="start", expected_state="stopped")
        self.assertEqual(start["phase"], "acknowledged")

    def test_poll_memory_error_preserves_original_row_and_object(self):
        row = self.submit()
        original = MemoryError("fictional poll failure")
        self.provider.hooks["task"] = failing(original)
        with self.assertRaises(MemoryError) as caught:
            self.poll(row)
        self.assertIs(caught.exception, original)
        self.assertEqual(self.store().get(row["id"], ACTOR), row)

    def test_action_requires_its_specific_source_state_before_admission(self):
        for index, (action, wrong_state) in enumerate((("start", "running"), ("shutdown", "stopped"))):
            with self.subTest(action=action):
                directory = self.root / ("wrong-source-state-" + str(index))
                directory.mkdir()
                self.cfg.data_dir = str(directory)
                self.provider.status["status"] = wrong_state
                before = list(self.provider.calls)
                self.assert_error("invalid_request", lambda: self.submit(
                    action=action, expected_state=wrong_state))
                self.assertEqual(self.provider.calls, before)
                self.assertFalse((directory / "lab-power").exists())

    def test_absent_original_session_callback_cannot_authorize_dispatch(self):
        self.service.still_current = None
        self.assert_error("session_retired", self.submit)
        self.assertEqual(self.provider.calls, [])

    def test_session_retired_during_replay_store_read_does_not_return_operation(self):
        request = self.request()
        self.service.submit(ACTOR, request)
        before = list(self.provider.calls)
        owner = self

        class RetiringReplay(LabPowerStore):
            def admit(self, *args):
                result = super().admit(*args)
                owner.current = False
                return result

        service = self.make_service(store_factory=RetiringReplay)
        self.assert_error("session_retired", lambda: service.submit(ACTOR, request))
        self.assertEqual(self.provider.calls, before)

    def test_inspect_rechecks_session_after_busy_store_lookup(self):
        owner = self

        class RetiringLookup(LabPowerStore):
            def active_for_target(self, target):
                result = super().active_for_target(target)
                owner.current = False
                return result

        service = self.make_service(store_factory=RetiringLookup)
        self.assert_error("session_retired", lambda: service.inspect(ACTOR))
        self.assert_no_submission()

    def test_any_reported_config_lock_rejects_before_control(self):
        original = self.provider.config.copy()
        for index, lock in enumerate(("backup", "snapshot", "migrate", "suspended", "unknown-lock", "", None, False)):
            with self.subTest(lock=lock):
                self.provider.config = {**original, "lock": lock}
                row = self.submit(request_key="locked-" + str(index))
                self.assertEqual((row["phase"], row["error"], row["active"]),
                                 ("rejected", "state_mismatch", 0))
        self.assert_no_submission()

    def test_shutdown_requires_actual_running_even_for_well_formed_request(self):
        self.provider.status["status"] = "stopped"
        row = self.submit(action="shutdown", expected_state="running")
        self.assertEqual((row["phase"], row["error"], row["active"]),
                         ("rejected", "state_mismatch", 0))
        self.assert_no_submission()

    def test_official_split_token_task_identity_can_complete_matching_operation(self):
        row = self.submit()
        self.provider.task_state, self.provider.task_exit = "stopped", "OK"
        self.provider.status["status"] = "running"
        document = self.provider.get_task(row["upid"])
        self.assertEqual((document["user"], document["tokenid"]), ("fixture@pve", "power"))
        result = self.poll(row)
        self.assertEqual((result["phase"], result["task_exit"], result["observed_state"]),
                         ("succeeded", "OK", "running"))

    def test_task_base_principal_without_exact_token_binding_cannot_complete(self):
        for index, tokenid in enumerate((None, "other-token")):
            with self.subTest(tokenid=tokenid):
                directory = self.root / ("token-binding-" + str(index))
                directory.mkdir()
                self.cfg.data_dir = str(directory)
                self.provider.status["status"] = "stopped"
                self.provider.hooks.clear()
                row = self.submit()
                document = {"upid": row["upid"], "node": "fictional-pve", "id": "5000",
                            "user": "fixture@pve", "type": "qmstart", "status": "stopped", "exitstatus": "OK"}
                if tokenid is not None:
                    document["tokenid"] = tokenid
                self.provider.hooks["task"] = lambda _upid: document
                self.provider.status["status"] = "running"
                submitted = [args for method, args in self.provider.calls if method == "submit"]
                result = self.poll(row)
                self.assertEqual(result["phase"], "acknowledged" if tokenid is None else "uncertain")
                self.assertEqual(result["active"], 1)
                self.assertIsNone(result["task_exit"])
                self.assertEqual(result["error"], "observation_unavailable" if tokenid is None else "invalid_response")
                self.assertEqual([args for method, args in self.provider.calls if method == "submit"], submitted)


if __name__ == "__main__":
    unittest.main()
