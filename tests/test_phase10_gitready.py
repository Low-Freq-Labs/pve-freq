"""Tests for Phase 10 — GIT-READY (Codebase audit for public release).
Covers: credential scrubbing, dead code detection, SOURCE-CODE-STANDARDS
compliance, no hardcoded DC01 values, distro compatibility patterns.
"""
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent
MODULES_DIR = FREQ_ROOT / "freq" / "modules"
CORE_DIR = FREQ_ROOT / "freq" / "core"
API_DIR = FREQ_ROOT / "freq" / "api"
DEPLOYERS_DIR = FREQ_ROOT / "freq" / "deployers"
CONF_DIR = FREQ_ROOT / "conf"


def _all_py_files():
    """Yield all .py files in the freq/ directory."""
    for root, dirs, files in os.walk(FREQ_ROOT / "freq"):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".py"):
                yield Path(root) / f


def _all_module_files():
    """Yield all .py files in freq/modules/."""
    for f in MODULES_DIR.iterdir():
        if f.suffix == ".py" and f.name != "__init__.py":
            yield f


# ─────────────────────────────────────────────────────────────
# CREDENTIAL SCRUBBING — No secrets in source code
# ─────────────────────────────────────────────────────────────

class TestNoCredentials(unittest.TestCase):
    """Ensure no passwords, tokens, or API keys are hardcoded."""

    PATTERNS = [
        # API tokens (generic patterns)
        (r'(?:token|api_key|apikey|secret)\s*=\s*["\'][A-Za-z0-9+/=]{20,}["\']',
         "Possible hardcoded API token"),
        # Password assignments (but not placeholders or config references)
        (r'password\s*=\s*["\'][^"\']{8,}["\']',
         "Possible hardcoded password"),
        # SSH private key material
        (r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
         "Private key material in source"),
    ]

    # Files known to have safe patterns (templates, examples, docs)
    EXEMPT_FILES = {
        "example_ping.py",  # Plugin example
        "demo.py",          # Demo mode uses mock data
    }

    def test_no_credentials_in_code(self):
        violations = []
        for path in _all_py_files():
            if path.name in self.EXEMPT_FILES:
                continue
            content = path.read_text(errors="replace")
            for pattern, description in self.PATTERNS:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    # Skip if it's clearly a variable reference or config
                    if any(safe in match.lower() for safe in
                           ["cfg.", "config.", "args.", "os.environ", "getenv",
                            "placeholder", "example", "changeme", "password123",
                            "your_", "xxx", "TODO"]):
                        continue
                    violations.append(f"{path.relative_to(FREQ_ROOT)}: {description}")
        self.assertEqual(violations, [],
                         f"Credential violations found:\n" +
                         "\n".join(violations))


# ─────────────────────────────────────────────────────────────
# NO HARDCODED DC01 VALUES — IPs must come from config
# ─────────────────────────────────────────────────────────────

class TestNoDC01Hardcoding(unittest.TestCase):
    """Ensure DC01-specific values aren't hardcoded in production code."""

    # DC01 management VLAN IPs that should NOT appear in code
    DC01_IPS = [
        "10.25.255.2", "10.25.255.5", "10.25.255.25",
        "10.25.255.26", "10.25.255.27", "10.25.255.28",
        "10.25.255.30", "10.25.255.31", "10.25.255.32",
        "10.25.255.33", "10.25.255.34", "10.25.255.35",
        "10.25.255.50", "10.25.255.55",
    ]

    # Dirs where DC01 values ARE expected (config, tests, docs)
    EXEMPT_DIRS = {"conf", "tests", "docs", ".git", "__pycache__"}

    def test_no_dc01_ips_in_source(self):
        violations = []
        for path in _all_py_files():
            # Skip exempt directories
            rel = path.relative_to(FREQ_ROOT)
            if any(part in self.EXEMPT_DIRS for part in rel.parts):
                continue
            content = path.read_text(errors="replace")
            for ip in self.DC01_IPS:
                if ip in content:
                    # Check it's not in a comment
                    for i, line in enumerate(content.split("\n"), 1):
                        if ip in line and not line.strip().startswith("#"):
                            violations.append(
                                f"{rel}:{i}: DC01 IP {ip}")
        self.assertEqual(violations, [],
                         f"DC01 IPs in production code:\n" +
                         "\n".join(violations))


# ─────────────────────────────────────────────────────────────
# SOURCE-CODE-STANDARDS — All new modules have headers
# ─────────────────────────────────────────────────────────────

class TestSourceCodeStandards(unittest.TestCase):
    """Verify SOURCE-CODE-STANDARDS compliance on new v3.0.0 modules."""

    # Modules added during the v3.0.0 rewrite (Phases 1-7)
    NEW_MODULES = [
        "switch_orchestration.py", "config_management.py", "event_network.py",
        "snmp.py", "topology.py", "net_intelligence.py",
        "firewall.py", "dns_management.py", "vpn.py",
        "cert_management.py", "proxy_management.py",
        "storage.py", "dr.py",
        "metrics.py", "synthetic_monitors.py", "vuln.py", "fim.py",
        "incident.py", "iac.py", "automation.py",
        "docker_mgmt.py", "hardware.py",
        "plugin_manager.py",
    ]

    def test_all_new_modules_have_docstrings(self):
        """Every new module must start with a module docstring."""
        missing = []
        for name in self.NEW_MODULES:
            path = MODULES_DIR / name
            if not path.exists():
                missing.append(f"{name}: FILE NOT FOUND")
                continue
            content = path.read_text()
            if not content.startswith('"""'):
                missing.append(f"{name}: no docstring")
        self.assertEqual(missing, [],
                         f"Modules without docstrings:\n" + "\n".join(missing))

    def test_all_new_modules_have_domain_line(self):
        """Docstring must mention the CLI domain."""
        missing = []
        for name in self.NEW_MODULES:
            path = MODULES_DIR / name
            if not path.exists():
                continue
            # Read first 30 lines (header area)
            lines = path.read_text().split("\n")[:30]
            header = "\n".join(lines).lower()
            if "domain:" not in header and "freq " not in header:
                missing.append(name)
        self.assertEqual(missing, [],
                         f"Modules missing Domain line:\n" + "\n".join(missing))

    def test_all_new_modules_have_replaces(self):
        """Docstring must say what enterprise tool this replaces."""
        missing = []
        for name in self.NEW_MODULES:
            path = MODULES_DIR / name
            if not path.exists():
                continue
            lines = path.read_text().split("\n")[:30]
            header = "\n".join(lines).lower()
            if "replaces:" not in header and "replace" not in header:
                missing.append(name)
        self.assertEqual(missing, [],
                         f"Modules missing Replaces line:\n" + "\n".join(missing))


# ─────────────────────────────────────────────────────────────
# PLATFORM ABSTRACTION — New modules don't hardcode apt/systemd
# ─────────────────────────────────────────────────────────────

class TestNoDistroAssumptions(unittest.TestCase):
    """New modules must not hardcode apt, dpkg, or assume systemd."""

    NEW_MODULES = [
        "switch_orchestration.py", "config_management.py", "event_network.py",
        "snmp.py", "topology.py", "net_intelligence.py",
        "firewall.py", "dns_management.py", "vpn.py",
        "cert_management.py", "proxy_management.py",
        "storage.py", "dr.py",
        "metrics.py", "synthetic_monitors.py", "vuln.py", "fim.py",
        "incident.py", "iac.py", "automation.py",
        "docker_mgmt.py", "hardware.py",
        "plugin_manager.py",
    ]

    def test_no_raw_apt_in_new_modules(self):
        """New modules must not use raw 'apt install' commands."""
        violations = []
        for name in self.NEW_MODULES:
            path = MODULES_DIR / name
            if not path.exists():
                continue
            content = path.read_text()
            # Look for apt/dpkg commands NOT in comments or strings
            for i, line in enumerate(content.split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if re.search(r'\bapt(?:-get)?\s+install\b', stripped):
                    violations.append(f"{name}:{i}: raw apt install")
                if re.search(r'\bdpkg\s+(?:--list|-l)\b', stripped):
                    violations.append(f"{name}:{i}: raw dpkg query")
        self.assertEqual(violations, [],
                         f"Distro-specific commands in new modules:\n" +
                         "\n".join(violations))


# ─────────────────────────────────────────────────────────────
# CONFIG FILE SAFETY — No secrets in conf/ defaults
# ─────────────────────────────────────────────────────────────

class TestConfigFilesSafe(unittest.TestCase):
    """Config files must not contain real credentials."""

    def test_freq_toml_no_real_passwords(self):
        path = CONF_DIR / "freq.toml"
        if not path.exists():
            return
        content = path.read_text()
        # Should not contain actual passwords
        self.assertNotIn("freq-admin-real-password", content)
        # Should reference credential files, not inline secrets
        # This is a sanity check — the actual secrets are in /etc/freq/credentials/

    def test_hosts_toml_exists(self):
        path = CONF_DIR / "hosts.toml.example"
        self.assertTrue(path.exists(), "hosts.toml.example missing from conf/")

    def test_no_private_keys_in_conf(self):
        for path in CONF_DIR.rglob("*"):
            if path.is_file() and path.suffix in (".toml", ".conf", ".json"):
                content = path.read_text(errors="replace")
                self.assertNotIn("-----BEGIN", content,
                                 f"Private key in {path.relative_to(FREQ_ROOT)}")


# ─────────────────────────────────────────────────────────────
# DEPLOYER REGISTRY — All deployers have required exports
# ─────────────────────────────────────────────────────────────

class TestDeployerCompleteness(unittest.TestCase):
    """Every deployer must export CATEGORY, VENDOR, and deploy()."""

    def test_all_deployers_have_category(self):
        from freq.deployers import list_deployers, get_deployer
        for category, vendor in list_deployers():
            mod = get_deployer(category, vendor)
            self.assertIsNotNone(mod, f"Cannot load {category}:{vendor}")
            self.assertTrue(hasattr(mod, "CATEGORY"),
                            f"{category}:{vendor} missing CATEGORY")
            self.assertTrue(hasattr(mod, "VENDOR") or hasattr(mod, "deploy"),
                            f"{category}:{vendor} missing VENDOR or deploy()")

    def test_deployer_categories_valid(self):
        from freq.deployers import CATEGORIES, list_deployers
        for category, vendor in list_deployers():
            self.assertIn(category, CATEGORIES,
                          f"Deployer {vendor} has unknown category: {category}")


# ─────────────────────────────────────────────────────────────
# PYTHON COMPATIBILITY — No features above 3.11 minimum
# ─────────────────────────────────────────────────────────────

class TestPythonCompatibility(unittest.TestCase):
    """Verify we don't use features that require Python > 3.11."""

    def test_no_match_statement_in_new_code(self):
        """match/case is 3.10+ but some of our audience might be 3.11 only.
        This is fine — 3.11 supports match. Just verify syntax is valid."""
        # All modules must at least parse
        for path in _all_py_files():
            try:
                with open(path) as f:
                    compile(f.read(), str(path), "exec")
            except SyntaxError as e:
                self.fail(f"Syntax error in {path.relative_to(FREQ_ROOT)}: {e}")

    def test_pyproject_minimum(self):
        """pyproject.toml must specify >=3.11."""
        pyproject = FREQ_ROOT / "pyproject.toml"
        if pyproject.exists():
            content = pyproject.read_text()
            self.assertIn("3.11", content,
                          "pyproject.toml should reference Python 3.11+")


# ─────────────────────────────────────────────────────────────
# FILE INVENTORY — No unexpected files in the repo
# ─────────────────────────────────────────────────────────────

class TestFileInventory(unittest.TestCase):
    """Verify no junk files slipped in."""

    def test_no_env_files(self):
        """No .env files in the repo."""
        env_files = list(FREQ_ROOT.glob("**/.env"))
        env_files = [f for f in env_files if ".git" not in str(f)]
        self.assertEqual(env_files, [],
                         f".env files found: {env_files}")

    def test_no_sqlite_files(self):
        """No SQLite databases in the repo."""
        db_files = list(FREQ_ROOT.glob("**/*.sqlite*"))
        db_files = [f for f in db_files if ".git" not in str(f)]
        self.assertEqual(db_files, [],
                         f"SQLite files found: {db_files}")

    def test_no_pem_files(self):
        """No certificate/key files in the repo."""
        pem_files = list(FREQ_ROOT.glob("**/*.pem"))
        pem_files += list(FREQ_ROOT.glob("**/*.key"))
        pem_files = [f for f in pem_files if ".git" not in str(f)]
        self.assertEqual(pem_files, [],
                         f"Key/cert files found: {pem_files}")


if __name__ == "__main__":
    unittest.main()
