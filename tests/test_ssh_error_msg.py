"""Tests for _ssh_error_msg — prove SSH error messages are never empty.

Bug: sshpass exit codes (5=wrong password, 6=host key unknown) produce
empty stderr. Before this fix, init showed 'Cannot connect ()' — no
actionable info for the user. Now _ssh_error_msg translates sshpass
exit codes into human-readable messages.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from freq.modules.init_cmd import _ssh_error_msg, _SSHPASS_ERRORS


class TestSshErrorMsg(unittest.TestCase):
    """Prove _ssh_error_msg never returns an empty or blank string."""

    def test_sshpass_wrong_password_not_empty(self):
        """sshpass exit 5 (wrong password) must produce a real message."""
        msg = _ssh_error_msg(5, "")
        self.assertTrue(msg.strip(), "exit 5 with empty stderr must not be blank")
        self.assertIn("wrong password", msg)

    def test_sshpass_host_key_unknown_not_empty(self):
        """sshpass exit 6 (host key unknown) must produce a real message."""
        msg = _ssh_error_msg(6, "")
        self.assertTrue(msg.strip(), "exit 6 with empty stderr must not be blank")
        self.assertIn("host key", msg)

    def test_all_sshpass_codes_produce_message(self):
        """Every known sshpass exit code must produce a non-empty message."""
        for code in _SSHPASS_ERRORS:
            msg = _ssh_error_msg(code, "")
            self.assertTrue(msg.strip(), f"exit {code} with empty stderr must not be blank")

    def test_unknown_nonzero_exit_not_empty(self):
        """Unknown non-zero exit codes must still produce something."""
        msg = _ssh_error_msg(99, "")
        self.assertTrue(msg.strip(), "unknown exit code with empty stderr must not be blank")
        self.assertIn("99", msg)

    def test_stderr_preserved_when_present(self):
        """When stderr has content, use it instead of the exit code."""
        msg = _ssh_error_msg(5, "Permission denied (publickey)")
        self.assertEqual(msg, "Permission denied (publickey)")

    def test_stderr_whitespace_only_uses_exit_code(self):
        """Whitespace-only stderr should fall through to exit code lookup."""
        msg = _ssh_error_msg(5, "   \n  ")
        self.assertIn("wrong password", msg)

    def test_no_empty_parens_in_connect_message(self):
        """The actual formatted error must never produce empty parens."""
        for rc in [0, 1, 3, 5, 6, 99, 255]:
            msg = _ssh_error_msg(rc, "")
            formatted = f"Cannot connect ({msg})"
            self.assertNotEqual(formatted, "Cannot connect ()",
                                f"rc={rc}: formatted message must not have empty parens")


if __name__ == "__main__":
    unittest.main()
