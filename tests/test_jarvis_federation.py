"""Tests for freq.jarvis.federation — multi-site federation."""
import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.case_matrix import run_case_matrix

from freq.jarvis.federation import (
    Site, load_sites, save_sites, register_site, unregister_site,
    _make_auth_header, verify_auth, poll_site, poll_all_sites,
    should_poll, sites_to_dicts, federation_summary,
    FEDERATION_FILE, POLL_INTERVAL,
)


class TestSiteIO(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_fed_io_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _case_load_missing_returns_empty(self):
        self.assertEqual(load_sites(self.tmpdir), [])

    def _case_save_and_load_roundtrip(self):
        sites = [Site(name="dc02", url="https://dc02.example.com:8888", secret="s3cr3t")]
        save_sites(self.tmpdir, sites)
        loaded = load_sites(self.tmpdir)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].name, "dc02")
        self.assertEqual(loaded[0].url, "https://dc02.example.com:8888")
        self.assertEqual(loaded[0].secret, "s3cr3t")

    def _case_load_corrupt_json(self):
        path = os.path.join(self.tmpdir, FEDERATION_FILE)
        with open(path, "w") as f:
            f.write("{{{bad")
        self.assertEqual(load_sites(self.tmpdir), [])

    def _case_load_empty_sites_list(self):
        path = os.path.join(self.tmpdir, FEDERATION_FILE)
        with open(path, "w") as f:
            json.dump({"sites": []}, f)
        self.assertEqual(load_sites(self.tmpdir), [])

    def _case_url_trailing_slash_stripped(self):
        sites = [Site(name="dc02", url="https://dc02.example.com:8888/")]
        save_sites(self.tmpdir, sites)
        loaded = load_sites(self.tmpdir)
        self.assertFalse(loaded[0].url.endswith("/"))


class TestRegistration(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_fed_reg_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _case_register_happy(self):
        ok, msg = register_site(self.tmpdir, "dc02", "https://dc02.example.com")
        self.assertTrue(ok)
        sites = load_sites(self.tmpdir)
        self.assertEqual(len(sites), 1)

    def _case_register_dup_name(self):
        register_site(self.tmpdir, "dc02", "https://dc02.example.com")
        ok, msg = register_site(self.tmpdir, "dc02", "https://other.example.com")
        self.assertFalse(ok)
        self.assertIn("already registered", msg)

    def _case_register_dup_url(self):
        register_site(self.tmpdir, "dc02", "https://dc02.example.com")
        ok, msg = register_site(self.tmpdir, "dc03", "https://dc02.example.com")
        self.assertFalse(ok)
        self.assertIn("already registered", msg)

    def _case_register_missing_fields(self):
        ok, msg = register_site(self.tmpdir, "", "https://dc02.example.com")
        self.assertFalse(ok)
        ok, msg = register_site(self.tmpdir, "dc02", "")
        self.assertFalse(ok)


class TestUnregistration(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_fed_unreg_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _case_unregister_happy(self):
        register_site(self.tmpdir, "dc02", "https://dc02.example.com")
        ok, msg = unregister_site(self.tmpdir, "dc02")
        self.assertTrue(ok)
        self.assertEqual(load_sites(self.tmpdir), [])

    def _case_unregister_not_found(self):
        ok, msg = unregister_site(self.tmpdir, "nonexistent")
        self.assertFalse(ok)
        self.assertIn("not found", msg)


class TestHMACAuth(unittest.TestCase):
    def _case_make_header_with_secret(self):
        headers = _make_auth_header("mysecret")
        self.assertIn("X-Freq-Timestamp", headers)
        self.assertIn("X-Freq-Signature", headers)

    def _case_make_header_no_secret(self):
        headers = _make_auth_header("")
        self.assertEqual(headers, {})

    def _case_verify_valid(self):
        secret = "test-secret"
        ts = str(int(time.time()))
        body = ""
        sig_input = f"{ts}:{body}"
        sig = hmac.new(secret.encode(), sig_input.encode(), hashlib.sha256).hexdigest()
        self.assertTrue(verify_auth(secret, ts, sig, body))

    def _case_verify_expired(self):
        secret = "test-secret"
        ts = str(int(time.time()) - 600)  # 10 min ago
        body = ""
        sig_input = f"{ts}:{body}"
        sig = hmac.new(secret.encode(), sig_input.encode(), hashlib.sha256).hexdigest()
        self.assertFalse(verify_auth(secret, ts, sig, body))

    def _case_verify_wrong_sig(self):
        self.assertFalse(verify_auth("secret", str(int(time.time())), "badsig"))

    def _case_verify_no_secret_passes(self):
        self.assertTrue(verify_auth("", "", ""))

    def _case_verify_bad_timestamp(self):
        self.assertFalse(verify_auth("secret", "not-a-number", "sig"))


class TestPolling(unittest.TestCase):
    @patch("freq.jarvis.federation.urllib.request.urlopen")
    def _case_poll_success(self, mock_urlopen):
        # Mock healthz response
        healthz_resp = MagicMock()
        healthz_resp.read.return_value = json.dumps({"version": "2.2.0"}).encode()
        healthz_resp.__enter__ = MagicMock(return_value=healthz_resp)
        healthz_resp.__exit__ = MagicMock(return_value=False)

        # Mock health response
        health_resp = MagicMock()
        health_resp.read.return_value = json.dumps({"hosts": [
            {"status": "ok"}, {"status": "ok"}, {"status": "unreachable"},
        ]}).encode()
        health_resp.__enter__ = MagicMock(return_value=health_resp)
        health_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [healthz_resp, health_resp]

        site = Site(name="dc02", url="https://dc02.example.com")
        result = poll_site(site)
        self.assertEqual(result.last_status, "ok")
        self.assertEqual(result.last_version, "2.2.0")
        self.assertEqual(result.last_hosts, 3)
        self.assertEqual(result.last_healthy, 2)

    @patch("freq.jarvis.federation.urllib.request.urlopen")
    def _case_poll_unreachable(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        site = Site(name="dc02", url="https://dc02.example.com")
        result = poll_site(site)
        self.assertEqual(result.last_status, "unreachable")

    def _case_poll_disabled_skipped(self):
        site = Site(name="dc02", url="https://dc02.example.com", enabled=False)
        result = poll_site(site)
        self.assertNotEqual(result.last_status, "ok")


class TestShouldPoll(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_fed_poll_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _case_no_sites_returns_false(self):
        self.assertFalse(should_poll(self.tmpdir))

    def _case_stale_sites_returns_true(self):
        sites = [Site(name="dc02", url="https://dc02.example.com", last_seen=time.time() - 300)]
        save_sites(self.tmpdir, sites)
        self.assertTrue(should_poll(self.tmpdir, interval=120))

    def _case_recent_sites_returns_false(self):
        sites = [Site(name="dc02", url="https://dc02.example.com", last_seen=time.time())]
        save_sites(self.tmpdir, sites)
        self.assertFalse(should_poll(self.tmpdir, interval=120))


class TestSerialization(unittest.TestCase):
    def _case_sites_to_dicts_hides_secret(self):
        sites = [Site(name="dc02", url="https://dc02.example.com", secret="s3cr3t")]
        dicts = sites_to_dicts(sites)
        self.assertEqual(len(dicts), 1)
        self.assertTrue(dicts[0]["has_secret"])
        self.assertNotIn("secret", dicts[0])

    def _case_sites_to_dicts_empty(self):
        self.assertEqual(sites_to_dicts([]), [])

    def _case_federation_summary(self):
        sites = [
            Site(name="dc02", url="u1", enabled=True, last_status="ok", last_hosts=10, last_healthy=8),
            Site(name="dc03", url="u2", enabled=True, last_status="unreachable", last_hosts=0, last_healthy=0),
            Site(name="dc04", url="u3", enabled=False, last_status="unknown"),
        ]
        summary = federation_summary(sites)
        self.assertEqual(summary["total_sites"], 3)
        self.assertEqual(summary["active_sites"], 2)
        self.assertEqual(summary["reachable_sites"], 1)
        self.assertEqual(summary["unreachable_sites"], 1)
        self.assertEqual(summary["total_hosts"], 10)
        self.assertEqual(summary["total_healthy"], 8)

    def _case_federation_summary_empty(self):
        summary = federation_summary([])
        self.assertEqual(summary["total_sites"], 0)
        self.assertEqual(summary["total_hosts"], 0)


FEDERATION_SITE_IO_CASES = (
    "_case_load_missing_returns_empty", "_case_save_and_load_roundtrip",
    "_case_load_corrupt_json", "_case_load_empty_sites_list",
    "_case_url_trailing_slash_stripped",
)
FEDERATION_REGISTRATION_CASES = (
    "_case_register_happy", "_case_register_dup_name", "_case_register_dup_url",
    "_case_register_missing_fields",
)
FEDERATION_UNREGISTRATION_CASES = (
    "_case_unregister_happy", "_case_unregister_not_found",
)
FEDERATION_HMAC_CASES = (
    "_case_make_header_with_secret", "_case_make_header_no_secret",
    "_case_verify_valid", "_case_verify_expired", "_case_verify_wrong_sig",
    "_case_verify_no_secret_passes", "_case_verify_bad_timestamp",
)
FEDERATION_POLLING_CASES = (
    "_case_poll_success", "_case_poll_unreachable", "_case_poll_disabled_skipped",
)
FEDERATION_SHOULD_POLL_CASES = (
    "_case_no_sites_returns_false", "_case_stale_sites_returns_true",
    "_case_recent_sites_returns_false",
)
FEDERATION_SERIALIZATION_CASES = (
    "_case_sites_to_dicts_hides_secret", "_case_sites_to_dicts_empty",
    "_case_federation_summary", "_case_federation_summary_empty",
)


class TestFederationSiteIOMatrix(unittest.TestCase):
    def test_federation_site_io_matrix(self):
        run_case_matrix(self, TestSiteIO, FEDERATION_SITE_IO_CASES)


class TestFederationRegistrationMatrix(unittest.TestCase):
    def test_federation_registration_matrix(self):
        run_case_matrix(self, TestRegistration, FEDERATION_REGISTRATION_CASES)


class TestFederationUnregistrationMatrix(unittest.TestCase):
    def test_federation_unregistration_matrix(self):
        run_case_matrix(self, TestUnregistration, FEDERATION_UNREGISTRATION_CASES)


class TestFederationHMACMatrix(unittest.TestCase):
    def test_federation_hmac_matrix(self):
        run_case_matrix(self, TestHMACAuth, FEDERATION_HMAC_CASES)


class TestFederationPollingMatrix(unittest.TestCase):
    def test_federation_polling_matrix(self):
        run_case_matrix(self, TestPolling, FEDERATION_POLLING_CASES)


class TestFederationShouldPollMatrix(unittest.TestCase):
    def test_federation_should_poll_matrix(self):
        run_case_matrix(self, TestShouldPoll, FEDERATION_SHOULD_POLL_CASES)


class TestFederationSerializationMatrix(unittest.TestCase):
    def test_federation_serialization_matrix(self):
        run_case_matrix(self, TestSerialization, FEDERATION_SERIALIZATION_CASES)


if __name__ == "__main__":
    unittest.main()
