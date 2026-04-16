""" — CLI / TUI parity with /api/health.

Sonny's correction: "This product-law/truth model is NOT web-only.
Raw commands and TUI are just as important. Backend work should keep
CLI/TUI/web aligned on the same state model: expected-vs-actual,
freshness, failure class, and evidence before action. No surface gets
to be vaguer than the others."

This contract pins the CLI read paths that currently print fleet host
status / health / reachability so they route through the same shared
classifier (freq.core.health_state) as the /api/health endpoints.

Surfaces pinned here:
  - freq fleet status (freq/modules/fleet.py cmd_status)
  - freq doctor _check_fleet_connectivity (freq/core/doctor.py)

The target behavior: both paths classify every failure through
`classify_probe_failure` and surface the six-state token + reason to
the operator, matching the web API's probe_state/probe_reason shape.
"""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO = Path(__file__).parent.parent
FLEET_PY = REPO / "freq" / "modules" / "fleet.py"
DOCTOR_PY = REPO / "freq" / "core" / "doctor.py"


class TestFleetStatusCmdUsesClassifier(unittest.TestCase):
    """freq fleet status (cmd_status in freq/modules/fleet.py) must
    route every failure through classify_probe_failure and surface the
    six-state reason in both JSON and table modes."""

    def _fleet_src(self):
        return FLEET_PY.read_text()

    def test_imports_health_state_classifier(self):
        src = self._fleet_src()
        self.assertIn("from freq.core.health_state import", src)
        self.assertIn("classify_probe_failure", src)
        self.assertIn("aggregate_probe_state", src)
        self.assertIn("STATE_LIVE", src)
        self.assertIn("STATE_AUTH_FAILED", src)
        self.assertIn("STATE_UNREACHABLE", src)
        self.assertIn("STATE_DEGRADED", src)

    def test_cmd_status_classifies_failures(self):
        src = self._fleet_src()
        start = src.find("def cmd_status(")
        self.assertGreater(start, 0)
        end = src.find("\ndef ", start + 10)
        window = src[start:end]
        # The pre-classifier body used `err = r.stderr[:30]`. It must
        # be replaced by a call to classify_probe_failure.
        self.assertIn("classify_probe_failure(", window,
                      "cmd_status must call the shared classifier")
        # Each classified entry carries a state and reason.
        self.assertIn('"state":', window)
        self.assertIn('"reason":', window)
        self.assertIn('"probed_at":', window)

    def test_cmd_status_table_surfaces_failure_class(self):
        """The DETAIL column must show auth_failed / degraded / etc.
        as explicit tokens on failure — not a raw stderr snippet."""
        src = self._fleet_src()
        start = src.find("def cmd_status(")
        end = src.find("\ndef ", start + 10)
        window = src[start:end]
        # Explicit state dispatch in the render loop.
        self.assertIn("STATE_LIVE", window)
        self.assertIn("STATE_AUTH_FAILED", window)
        self.assertIn("STATE_DEGRADED", window)
        # DETAIL column replaces the old UPTIME-only column so state
        # reasons get a column of their own.
        self.assertIn('("DETAIL", 38)', window)

    def test_cmd_status_json_emits_probe_state(self):
        src = self._fleet_src()
        start = src.find("def cmd_status(")
        end = src.find("\ndef ", start + 10)
        window = src[start:end]
        self.assertIn('"probe_state": probe_state', window)
        self.assertIn('"probe_reason": probe_reason', window)


class TestFleetStatusLiveClassification(unittest.TestCase):
    """Run cmd_status against a mocked ssh layer to verify the CLI
    output reflects every six-state class correctly, not just boolean
    up/down. Uses JSON mode to avoid ANSI escape parsing."""

    def _make_host(self, label, ip, htype):
        class H:
            pass
        h = H()
        h.label = label
        h.ip = ip
        h.htype = htype
        h.groups = ""
        return h

    def test_mixed_state_fleet_surfaces_each_class(self):
        from freq.modules import fleet as fleet_mod
        from freq.core.types import CmdResult

        hosts = [
            self._make_host("pve01", "10.0.0.1", "pve"),
            self._make_host("nexus", "10.0.0.2", "linux"),
            self._make_host("truenas-lab", "10.0.0.3", "truenas"),
            self._make_host("idrac-10", "10.0.0.10", "idrac"),
        ]

        # Fake ssh_run_many that returns per-host CmdResult with
        # different failure classes: one LIVE, one AUTH_FAILED, one
        # UNREACHABLE, one operator-auth-issue legacy device.
        fake_results = {
            "10.0.0.1": CmdResult(
                returncode=0, stdout="up 3 days", stderr="", duration=0.1,
            ),
            "10.0.0.2": CmdResult(
                returncode=255, stdout="",
                stderr="Permission denied (publickey).",
                duration=0.2,
            ),
            "10.0.0.3": CmdResult(
                returncode=255, stdout="",
                stderr="ssh: connect to host 10.0.0.3 port 22: Connection timed out",
                duration=3.0,
            ),
            "10.0.0.10": CmdResult(
                returncode=255, stdout="",
                stderr="Permission denied (publickey,password).",
                duration=0.5,
            ),
        }

        class FakeCfg:
            pass

        cfg = FakeCfg()
        cfg.hosts = hosts
        cfg.ssh_key_path = "/tmp/fake-key"
        cfg.ssh_rsa_key_path = "/tmp/fake-rsa-key"
        cfg.ssh_connect_timeout = 3
        cfg.ssh_max_parallel = 5
        cfg.data_dir = "/tmp"

        args = mock.Mock()
        args.json_output = True

        def fake_run_many(hosts, command, **kw):
            return {h.ip: fake_results.get(h.ip) for h in hosts}

        def fake_result_for(results, h):
            return results.get(h.ip)

        buf = io.StringIO()
        with mock.patch.object(fleet_mod, "ssh_run_many", side_effect=fake_run_many), \
             mock.patch.object(fleet_mod, "result_for", side_effect=fake_result_for), \
             mock.patch.object(fleet_mod, "_load_dashboard_health_cache", return_value={}), \
             mock.patch("sys.stdout", buf):
            rc = fleet_mod.cmd_status(cfg, None, args)

        out = buf.getvalue()
        payload = json.loads(out)

        # Top-level probe_state must be auth_failed (worst wins over
        # unreachable since pve01 is live; real fleet has nexus and
        # truenas-lab in different error classes).
        self.assertEqual(payload["probe_state"], "auth_failed")
        self.assertIn("nexus", payload["probe_reason"])
        self.assertIn("auth", payload["probe_reason"].lower())

        # Per-host classification.
        by_label = {h["label"]: h for h in payload["hosts"]}
        self.assertEqual(by_label["pve01"]["state"], "live")
        self.assertEqual(by_label["nexus"]["state"], "auth_failed")
        self.assertIn("auth", by_label["nexus"]["reason"].lower())
        self.assertEqual(by_label["truenas-lab"]["state"], "unreachable")
        self.assertIn("unreachable", by_label["truenas-lab"]["reason"].lower())
        # idrac with operator auth issue still classifies as auth_failed
        # in the state field — the operator-auth-issue flag only affects
        # the table render (n/a column), not the underlying state truth.
        self.assertEqual(by_label["idrac-10"]["state"], "auth_failed")

        # Legacy status alias preserved for existing JSON consumers.
        self.assertEqual(by_label["pve01"]["status"], "online")
        self.assertEqual(by_label["nexus"]["status"], "offline")

        # JSON mode always returns 0 (same as prior contract) — the
        # nonzero exit code lives only in the human table path.
        self.assertEqual(rc, 0)
        # online/offline counters reflect the classification.
        self.assertEqual(payload["online"], 1)
        self.assertEqual(payload["offline"], 3)


class TestFleetDashboardCmdUsesClassifier(unittest.TestCase):
    """freq fleet dashboard (cmd_dashboard in freq/modules/fleet.py)
    must route every failure through classify_probe_failure so the
    table names the failure class alongside the metric columns."""

    def _fleet_src(self):
        return FLEET_PY.read_text()

    def test_cmd_dashboard_classifies_failures(self):
        src = self._fleet_src()
        start = src.find("def cmd_dashboard(")
        self.assertGreater(start, 0)
        end = src.find("\ndef ", start + 10)
        window = src[start:end]
        self.assertIn("classify_probe_failure(", window,
                      "cmd_dashboard must route failures through the classifier")
        self.assertIn("STATE_AUTH_FAILED", window)
        self.assertIn("aggregate_probe_state(", window)

    def test_cmd_dashboard_summary_surfaces_probe_state(self):
        src = self._fleet_src()
        start = src.find("def cmd_dashboard(")
        end = src.find("\ndef ", start + 10)
        window = src[start:end]
        self.assertIn("fleet state:", window,
                      "dashboard summary must surface probe_state parity")


class TestFleetHealthCmdUsesClassifier(unittest.TestCase):
    """freq fleet health (cmd_health in freq/modules/health.py) must
    classify probe failures through the shared helper. Metric-based
    load grading (healthy/degraded/critical) is a different axis and
    stays as-is, but unreachable/auth_failed hosts must no longer be
    silently collapsed into 'critical'."""

    def _health_src(self):
        return (REPO / "freq" / "modules" / "health.py").read_text()

    def test_imports_classifier_and_states(self):
        src = self._health_src()
        self.assertIn("from freq.core.health_state import", src)
        self.assertIn("classify_probe_failure", src)
        self.assertIn("STATE_AUTH_FAILED", src)
        self.assertIn("STATE_UNREACHABLE", src)

    def test_failure_path_classifies(self):
        src = self._health_src()
        start = src.find("def cmd_health(")
        self.assertGreater(start, 0)
        end = src.find("\ndef ", start + 10)
        if end < 0:
            end = len(src)
        window = src[start:end]
        # Failure branch routes through the classifier.
        self.assertIn("classify_probe_failure(rc, stderr, stdout)", window)
        # Auth / unreachable / degraded counters exist alongside the
        # metric grading.
        self.assertIn("auth_failed_n", window)
        self.assertIn("unreachable_n", window)
        # Summary names the worst probe failure.
        self.assertIn("worst probe:", window)

    def test_return_code_escalates_on_probe_failure(self):
        """A host that is auth_failed or unreachable must push the
        exit code non-zero even if no host is in the 'critical' metric
        class. This is how `freq fleet health` becomes useful in CI."""
        src = self._health_src()
        self.assertIn(
            "return 1 if (critical > 0 or auth_failed_n > 0 or unreachable_n > 0) else 0",
            src,
        )


class TestFleetNtpCmdUsesClassifier(unittest.TestCase):
    """freq fleet ntp check (cmd_ntp in freq/modules/fleet.py) must
    classify probe failures through the shared helper and distinguish
    probe-failed (auth_failed / unreachable / degraded) from ntp-drift
    (clock not synced / timesyncd inactive), which are different
    classes that previously collapsed into a single 'down'."""

    def _fleet_src(self):
        return FLEET_PY.read_text()

    def test_cmd_ntp_classifies_probe_failures(self):
        src = self._fleet_src()
        start = src.find("def cmd_ntp(")
        self.assertGreater(start, 0)
        end = src.find("\ndef ", start + 10)
        window = src[start:end]
        self.assertIn("classify_probe_failure(", window)
        self.assertIn("probe_failures", window)
        self.assertIn("ntp_drift", window)

    def test_cmd_ntp_names_worst_case(self):
        src = self._fleet_src()
        start = src.find("def cmd_ntp(")
        end = src.find("\ndef ", start + 10)
        window = src[start:end]
        self.assertIn("worst:", window,
                      "ntp summary must name the worst failing host + reason")
        self.assertIn('("TIME / REASON', window)


class TestFleetUpdateCmdUsesClassifier(unittest.TestCase):
    """freq fleet update check (cmd_fleet_update in fleet.py) must
    classify probe failures through the shared helper so an
    unreachable host doesn't silently disappear into the update count."""

    def _fleet_src(self):
        return FLEET_PY.read_text()

    def test_cmd_fleet_update_classifies_probe_failures(self):
        src = self._fleet_src()
        start = src.find("def cmd_fleet_update(")
        self.assertGreater(start, 0)
        end = src.find("\ndef ", start + 10)
        window = src[start:end]
        self.assertIn("classify_probe_failure(", window)
        self.assertIn("probe_failures", window)
        # REASON column added so each row can carry the state+reason.
        self.assertIn('("REASON', window)

    def test_cmd_fleet_update_summary_surfaces_probe_failures(self):
        src = self._fleet_src()
        start = src.find("def cmd_fleet_update(")
        end = src.find("\ndef ", start + 10)
        window = src[start:end]
        self.assertIn("probe_failed — not counted", window,
                      "update summary must call out probe_failed hosts "
                      "separately from the update count")
        # Non-zero exit on probe failures so CI can fail on missing data.
        self.assertIn("return 1 if probe_failures else 0", window)


class TestDoctorFleetConnectivityUsesClassifier(unittest.TestCase):
    """_check_fleet_connectivity in freq/core/doctor.py must route
    every failure through classify_probe_failure so the doctor's
    terminal output names the failure class (auth_failed / unreachable
    / degraded) instead of collapsing to 'down'."""

    def _doctor_src(self):
        return DOCTOR_PY.read_text()

    def test_imports_shared_classifier(self):
        src = self._doctor_src()
        idx = src.find("def _check_fleet_connectivity(")
        self.assertGreater(idx, 0)
        end = src.find("\ndef ", idx + 10)
        window = src[idx:end]
        self.assertIn("from freq.core.health_state import", window)
        self.assertIn("classify_probe_failure", window)

    def test_breakdown_surfaces_failure_class(self):
        src = self._doctor_src()
        idx = src.find("def _check_fleet_connectivity(")
        end = src.find("\ndef ", idx + 10)
        window = src[idx:end]
        # Step messages must name the classes — not just a count.
        self.assertIn('auth_failed', window)
        self.assertIn('unreachable', window)
        self.assertIn('degraded', window)
        # Worst-host reason surfaced in the step_warn/step_fail output.
        self.assertIn("worst_reason_by_state", window)
        # Fleet SSH step message still exists, now with six-state vocab.
        self.assertTrue(
            '"Fleet SSH: ' in window or "'Fleet SSH: " in window or
            'f"Fleet SSH: ' in window,
            "fleet ssh step message must exist",
        )

    def test_legacy_reachable_language_dropped(self):
        """The pre-contract code said 'reachable'; new language is
        'live' to match the six-state vocabulary. Parity check."""
        src = self._doctor_src()
        idx = src.find("def _check_fleet_connectivity(")
        end = src.find("\ndef ", idx + 10)
        window = src[idx:end]
        # At least one step message should use 'live' in the Fleet SSH
        # summary so the vocabulary across CLI matches /api/health.
        # (We keep the old 'reachable' variable names internally as a
        # counter but the user-facing string is 'live'.)
        self.assertIn('/{total_checkable} live', window)


if __name__ == "__main__":
    unittest.main()
