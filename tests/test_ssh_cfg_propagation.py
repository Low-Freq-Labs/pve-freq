"""Consumer contract test: SSH calls must propagate cfg to use configured service account.

Bug fixed: 58 SSH calls across api/ and serve.py were missing cfg=cfg,
causing them to default to 'freq-admin' instead of the configured 'freq-ops'.
The health background probe (which passed cfg) worked; all API endpoints did not.
"""

import ast
import os
import unittest

# Files that contain consumer-side SSH calls
CONSUMER_FILES = [
    "freq/api/fleet.py",
    "freq/api/docker_api.py",
    "freq/api/vm.py",
    "freq/api/secure.py",
    "freq/api/backup_verify.py",
    "freq/api/logs.py",
    "freq/api/hw.py",
    "freq/api/net.py",
    "freq/modules/serve.py",
    "freq/modules/fleet.py",
]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _CfgChecker(ast.NodeVisitor):
    """AST visitor that finds ssh_single/run_many calls missing cfg=."""

    SSH_FUNCS = {"ssh_single", "ssh_run_many", "run_many", "ssh_run_many_fn", "ssh_fn", "ssh_run"}

    def __init__(self):
        self.missing = []  # (lineno, func_name, file)

    def visit_Call(self, node):
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        if func_name in self.SSH_FUNCS:
            has_cfg = any(
                kw.arg == "cfg" for kw in node.keywords
            )
            if not has_cfg:
                self.missing.append((node.lineno, func_name))

        self.generic_visit(node)


class TestSSHCfgPropagation(unittest.TestCase):
    """Every consumer-side SSH call must pass cfg=cfg."""

    def test_all_ssh_calls_have_cfg(self):
        """No ssh_single/run_many call in consumer files should be missing cfg=."""
        all_missing = []
        for relpath in CONSUMER_FILES:
            fpath = os.path.join(REPO_ROOT, relpath)
            if not os.path.isfile(fpath):
                continue
            with open(fpath) as f:
                tree = ast.parse(f.read(), filename=relpath)
            checker = _CfgChecker()
            checker.visit(tree)
            for lineno, func_name in checker.missing:
                all_missing.append(f"  {relpath}:{lineno} {func_name}() missing cfg=cfg")

        self.assertEqual(
            all_missing,
            [],
            f"SSH calls missing cfg=cfg (would default to wrong user):\n"
            + "\n".join(all_missing),
        )

    def test_configured_user_is_not_default(self):
        """freq.toml must set ssh service_account != hardcoded default."""
        from freq.core.config import load_config, _DEFAULTS

        cfg = load_config()
        self.assertNotEqual(
            cfg.ssh_service_account,
            "",
            "ssh_service_account must not be empty",
        )
        # The configured user should match what's in freq.toml
        self.assertEqual(cfg.ssh_service_account, "freq-ops")
        # And the default is freq-admin — different from configured
        self.assertEqual(_DEFAULTS["ssh_service_account"], "freq-admin")

    def test_containers_toml_state_is_honest(self):
        """container_vms reflects what containers.toml actually has (not faked)."""
        from freq.core.config import load_config

        cfg = load_config()
        containers_path = os.path.join(cfg.conf_dir, "containers.toml")
        if not os.path.isfile(containers_path):
            self.assertEqual(len(cfg.container_vms), 0,
                             "No containers.toml → container_vms must be empty")
            return
        with open(containers_path) as f:
            content = f.read()
        # If file is all comments/empty, container_vms should be empty
        has_real_entries = any(
            line.strip() and not line.strip().startswith("#")
            for line in content.split("\n")
        )
        if not has_real_entries:
            self.assertEqual(len(cfg.container_vms), 0,
                             "containers.toml is all comments → container_vms must be empty")


class TestHealthApiCLIParity(unittest.TestCase):
    """Health API probe and CLI fleet status must use the same auth path."""

    def test_health_probe_no_sudo(self):
        """Health status commands are read-only — must not use sudo."""
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        probe = src.split("def _bg_probe_health")[1].split("\ndef _bg_")[0]
        # The probe_host inner function should set use_sudo = False
        self.assertIn("use_sudo = False", probe,
                       "Health probe must not use sudo for read-only status commands")

    def test_fleet_status_has_cfg(self):
        """CLI fleet status must pass cfg=cfg for consistent user resolution."""
        with open(os.path.join(REPO_ROOT, "freq/modules/fleet.py")) as f:
            src = f.read()
        status_fn = src.split("def cmd_status")[1].split("\ndef ")[0]
        self.assertIn("cfg=cfg", status_fn,
                       "fleet status ssh_run_many must pass cfg=cfg")

    def test_both_paths_no_sudo(self):
        """Both CLI fleet status and API health must use use_sudo=False."""
        with open(os.path.join(REPO_ROOT, "freq/modules/fleet.py")) as f:
            fleet_src = f.read()
        status_fn = fleet_src.split("def cmd_status")[1].split("\ndef ")[0]
        self.assertIn("use_sudo=False", status_fn,
                       "CLI fleet status must not use sudo")

        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            serve_src = f.read()
        probe = serve_src.split("def _bg_probe_health")[1].split("\ndef _bg_")[0]
        self.assertIn("use_sudo = False", probe,
                       "API health probe must not use sudo")


if __name__ == "__main__":
    unittest.main()
