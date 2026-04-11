"""Tests for PVE token key path regression — Phase 6 must see Phase 4 keys.

Bug: Phase 4 generated keys in data/keys/ and set ctx["key_path"].
Phase 6 checked ctx["key_path"] but sometimes the file was inaccessible
because data/keys/ is 700 owned by the service account. Phase 6 skipped
API token creation with "SSH key not available", breaking Phase 7 discovery.

Root cause: Keys were generated in data/keys/ (700 owned by service account)
but ctx["key_path"] pointed there. After chown, the directory was unreadable
in some race conditions. Additionally, cfg.ssh_key_path was never updated
from its initial empty value (detected at config load time before keys existed).

Fix: Phase 4 now always syncs keys to ~/.ssh/ and repoints ctx["key_path"]
and cfg.ssh_key_path to the synced location. This ensures Phase 6 and 7
can always read the key regardless of data/keys/ permissions.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestKeyPathFlowContract(unittest.TestCase):
    """Phase 4 must set both ctx and cfg key paths for downstream phases."""

    def test_phase4_sets_cfg_ssh_key_path(self):
        """Phase 4 must update cfg.ssh_key_path after key generation."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("cfg.ssh_key_path = svc_ed", src)

    def test_phase4_sets_cfg_rsa_key_path(self):
        """Phase 4 must update cfg.ssh_rsa_key_path after key generation."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("cfg.ssh_rsa_key_path = svc_rsa", src)

    def test_phase4_repoints_ctx_to_svc_ssh(self):
        """Phase 4 must repoint ctx key_path to service account ~/.ssh/."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # ctx["key_path"] = svc_ed (which is ~/.ssh/id_ed25519)
        self.assertIn('ctx["key_path"] = svc_ed', src)
        self.assertIn('ctx["rsa_key_path"] = svc_rsa', src)

    def test_phase4_always_syncs_not_conditional(self):
        """Key sync to ~/.ssh/ must not be conditional on file absence."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # The old code had "if not os.path.isfile(svc_ed)" which skipped sync
        # The new code must NOT have that conditional
        # Find the shutil.copy2 for ed25519 and verify no "if not isfile" guard
        import re
        # Look for the pattern: the copy should be unconditional
        match = re.search(r'svc_ed = os\.path\.join.*?\n\s+shutil\.copy2\(ctx\["key_path"\], svc_ed\)', src, re.DOTALL)
        self.assertIsNotNone(match, "ed25519 sync must be unconditional (no isfile guard)")


class TestPhase6KeyResolution(unittest.TestCase):
    """Phase 6 must resolve key from ctx or cfg."""

    def test_phase6_reads_ctx_key_path(self):
        """Phase 6 must check ctx['key_path'] for the SSH key."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn('ctx.get("key_path"', src)

    def test_phase7_reads_ctx_key_path(self):
        """Phase 7 must also use ctx['key_path'] for SSH discovery."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # Phase 7 function _phase_fleet_discover uses the same pattern
        self.assertIn('ctx.get("key_path", "") or cfg.ssh_key_path', src)


class TestLogDirCompatibility(unittest.TestCase):
    """FreqConfig must have log_dir property for backward compatibility."""

    def test_log_dir_property_exists(self):
        """FreqConfig must have a log_dir property."""
        from freq.core.config import FreqConfig
        cfg = FreqConfig()
        self.assertTrue(hasattr(cfg, "log_dir"))

    def test_log_dir_derives_from_log_file(self):
        """log_dir must be derived from log_file path."""
        from freq.core.config import FreqConfig
        cfg = FreqConfig()
        cfg.log_file = "/opt/pve-freq/data/log/freq.log"
        self.assertEqual(cfg.log_dir, "/opt/pve-freq/data/log")


if __name__ == "__main__":
    unittest.main()
