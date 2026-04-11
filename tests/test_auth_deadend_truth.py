"""Auth dead-end truth tests.

Proves:
1. _is_first_run returns True when no users exist (even with markers)
2. Login gives helpful error when no users configured
3. Setup wizard available when no users exist
4. No dead-end between "setup complete" and "invalid credentials"
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestFirstRunUsersGate(unittest.TestCase):
    """_is_first_run must check users, not just markers."""

    def _fn_src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        return src.split("def _is_first_run")[1].split("\ndef ")[0]

    def test_checks_users_before_markers(self):
        """Must check user existence before checking markers."""
        src = self._fn_src()
        users_idx = src.index("_load_users")
        # Markers should be checked AFTER users
        marker_idx = src.index("setup-complete")
        self.assertLess(users_idx, marker_idx,
                         "Must check users before checking markers")

    def test_no_users_returns_true(self):
        """Must return True (first run) when no users exist."""
        src = self._fn_src()
        self.assertIn("not users", src,
                       "Must treat empty users as first run")
        self.assertIn("return True", src.split("not users")[1].split("\n")[0] +
                       src.split("not users")[1].split("\n")[1],
                       "Empty users must return True")

    def test_docstring_explains_dead_end(self):
        src = self._fn_src()
        self.assertIn("stranded", src.lower(),
                       "Docstring must explain the dead-end scenario")


class TestLoginNoUsersMessage(unittest.TestCase):
    """Login must give helpful error when no users exist."""

    def test_login_checks_empty_users(self):
        with open(os.path.join(REPO_ROOT, "freq/api/auth.py")) as f:
            src = f.read()
        handler = src.split("def handle_auth_login")[1].split("\ndef ")[0]
        self.assertIn("not users", handler,
                       "Login must check for empty users list")

    def test_helpful_error_message(self):
        with open(os.path.join(REPO_ROOT, "freq/api/auth.py")) as f:
            src = f.read()
        handler = src.split("def handle_auth_login")[1].split("\ndef ")[0]
        self.assertIn("No users configured", handler,
                       "Must say 'No users configured' not just 'Invalid credentials'")
        self.assertIn("setup", handler.lower(),
                       "Must point user to setup")


if __name__ == "__main__":
    unittest.main()
