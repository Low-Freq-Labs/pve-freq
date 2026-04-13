"""Empty state evidence contract tests.

Proves the long tail of empty/absent/error states in the dashboard
shell reads like production evidence with next-action clarity, not
consumer-app scaffolding. DC01 operators need to see:

1. Factual counts ("0 containers") instead of chatter ("No containers.")
2. Explicit next-action when applicable (probe endpoint, tag command,
   freq CLI invocation)
3. No decorative emoji glyphs (es-icon divs) padding empty states
4. "probe failed" on catch branches, not "X unavailable" / "X check failed"

These assertions target a representative set of surfaces across
FLEET, DOCKER, MEDIA, OPS, and SECURITY so regressing any one
category trips the test.
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
        return f.read()


class TestNoConsumerScaffoldingCopy(unittest.TestCase):
    """Old 'No X' consumer scaffolding phrasing must be gone from the
    surfaces flagged by Finn."""

    def test_no_containers_period(self):
        src = _js()
        self.assertNotIn(">No containers.</p>", src,
                          "Must not use 'No containers.' — use '0 containers'")
        self.assertNotIn(">No containers found.</p>", src,
                          "Must not use 'No containers found.'")

    def test_no_vlans_configured_old(self):
        src = _js()
        self.assertNotIn(">No VLANs configured</p>", src,
                          "Must use '0 VLANs configured' not 'No VLANs configured'")

    def test_no_ntp_data(self):
        src = _js()
        self.assertNotIn(">No NTP data</p>", src,
                          "Must describe 0-host probe result, not 'No NTP data'")

    def test_no_data_unqualified(self):
        src = _js()
        self.assertNotIn(">No data</p>", src,
                          "Must not use unqualified 'No data'")

    def test_no_storage_pools_detected_old(self):
        src = _js()
        self.assertNotIn(">No storage pools detected</p>", src,
                          "Must use '0 storage pools detected'")

    def test_no_deploy_history_old(self):
        src = _js()
        self.assertNotIn(">No deploy history</p>", src,
                          "Must use '0 deploys recorded'")

    def test_no_users_registered_old(self):
        src = _js()
        self.assertNotIn(">No users registered.</p>", src,
                          "Must use '0 users in users.conf'")

    def test_no_api_keys_stored(self):
        src = _js()
        self.assertNotIn("No API keys stored in vault.", src,
                          "Must use '0 API keys in vault'")

    def test_no_vault_empty(self):
        src = _js()
        self.assertNotIn(">Vault is empty.</p>", src,
                          "Must use '0 vault entries'")

    def test_no_agents_registered_old(self):
        src = _js()
        self.assertNotIn(">No agents registered.", src,
                          "Must use '0 agents registered'")

    def test_no_vms_found_on_cluster(self):
        src = _js()
        self.assertNotIn(">No VMs found on cluster.</p>", src,
                          "Must use '0 VMs on cluster'")

    def test_no_journal_entries_yet(self):
        src = _js()
        self.assertNotIn(">No journal entries yet.</p>", src,
                          "Must use '0 journal entries'")

    def test_no_lab_tools_visible_old(self):
        src = _js()
        self.assertNotIn(">No lab tools visible.</p>", src,
                          "Must use '0 lab tools visible'")

    def test_no_recent_activity_old(self):
        src = _js()
        self.assertNotIn(">No recent activity</p>", src,
                          "Must use '0 recent events'")

    def test_no_monitors_configured_old(self):
        src = _js()
        self.assertNotIn(">No monitors configured</p>", src,
                          "Must use '0 monitors configured'")


class TestProbeFailedLanguageOnCatch(unittest.TestCase):
    """Catch branches must say 'probe failed' with endpoint guidance,
    not 'X check failed' or 'X unavailable'."""

    def test_ntp_catch_is_probe_failed(self):
        src = _js()
        self.assertNotIn(">NTP check failed</p>", src,
                          "NTP catch must say 'NTP probe failed'")
        self.assertIn("NTP probe failed", src)

    def test_snapshot_catch_is_probe_failed(self):
        src = _js()
        self.assertNotIn(">Snapshot check failed</p>", src,
                          "Snapshot catch must say 'snapshot probe failed'")
        self.assertIn("snapshot probe failed", src)

    def test_storage_catch_is_probe_failed(self):
        src = _js()
        self.assertNotIn(">Storage check failed</p>", src,
                          "Storage catch must say 'storage probe failed'")
        self.assertIn("storage probe failed", src)

    def test_heatmap_catch_is_probe_failed(self):
        src = _js()
        self.assertNotIn(">Heatmap unavailable</p>", src,
                          "Heatmap catch must say 'heatmap probe failed'")
        self.assertIn("heatmap probe failed", src)

    def test_monitor_catch_is_probe_failed(self):
        src = _js()
        self.assertNotIn(">Monitor check failed</p>", src,
                          "Monitor catch must say 'monitor probe failed'")
        self.assertIn("monitor probe failed", src)

    def test_activity_catch_is_probe_failed(self):
        src = _js()
        self.assertNotIn(">Activity feed unavailable</p>", src,
                          "Activity catch must say 'activity probe failed'")
        self.assertIn("activity probe failed", src)


class TestNoDecorativeEmojiInEmptyStates(unittest.TestCase):
    """The decorative es-icon divs padding empty states must be gone
    from the surfaces listed by Finn."""

    def test_no_es_icon_in_user_list_empty(self):
        src = _js()
        # The old user-list empty state had a 👤 glyph — grep for it next
        # to 'users in users.conf' to confirm it's gone
        idx = src.find("0 users in users.conf")
        self.assertGreater(idx, 0)
        window = src[max(0, idx - 200): idx]
        self.assertNotIn("es-icon", window,
                          "User list empty state must not have decorative es-icon")

    def test_no_es_icon_in_vault_empty(self):
        src = _js()
        idx = src.find("0 vault entries")
        self.assertGreater(idx, 0)
        window = src[max(0, idx - 200): idx]
        self.assertNotIn("es-icon", window,
                          "Vault empty state must not have decorative es-icon")

    def test_no_es_icon_in_api_keys_empty(self):
        src = _js()
        idx = src.find("0 API keys in vault")
        self.assertGreater(idx, 0)
        window = src[max(0, idx - 200): idx]
        self.assertNotIn("es-icon", window,
                          "API keys empty state must not have decorative es-icon")

    def test_no_es_icon_in_vms_empty(self):
        src = _js()
        idx = src.find("0 VMs on cluster")
        self.assertGreater(idx, 0)
        window = src[max(0, idx - 200): idx]
        self.assertNotIn("es-icon", window,
                          "VMs empty state must not have decorative es-icon")

    def test_no_es_icon_in_journal_empty(self):
        src = _js()
        idx = src.find("0 journal entries")
        self.assertGreater(idx, 0)
        window = src[max(0, idx - 200): idx]
        self.assertNotIn("es-icon", window,
                          "Journal empty state must not have decorative es-icon")


class TestTdarrNoGreenTheater(unittest.TestCase):
    """The Tdarr widget had a ✅ green checkmark + 'Tdarr Running' label.
    Must be replaced with factual lowercase 'tdarr up'."""

    def test_no_tdarr_checkmark(self):
        src = _js()
        # The ✅ glyph (\u2705) must not appear near tdarr
        idx = src.find("w-tdarr")
        self.assertGreater(idx, 0)
        block = src[idx: idx + 2000]
        self.assertNotIn("\u2705", block,
                          "tdarr widget must not use ✅ checkmark")
        self.assertNotIn("Tdarr Running", block,
                          "tdarr widget must not use 'Tdarr Running' title case")

    def test_tdarr_says_lowercase_up(self):
        src = _js()
        idx = src.find("w-tdarr")
        block = src[idx: idx + 2000]
        self.assertIn("tdarr up", block,
                       "tdarr widget must report 'tdarr up' lowercase")

    def test_tdarr_not_detected_is_not_installed(self):
        """'Tdarr not detected' is soft. Use 'tdarr not installed'."""
        src = _js()
        self.assertNotIn("Tdarr not detected", src)
        self.assertIn("tdarr not installed", src)


if __name__ == "__main__":
    unittest.main()
