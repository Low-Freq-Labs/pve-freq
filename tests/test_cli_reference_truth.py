"""Regression tests for CLI-REFERENCE.md truthfulness.

Proves: every domain listed in CLI-REFERENCE.md exists as a registered
command in cli.py, and critical top-level commands are documented.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _get_cli_commands():
    """Get all top-level CLI command names from cli.py."""
    cli_path = os.path.join(REPO_ROOT, "freq", "cli.py")
    with open(cli_path) as f:
        src = f.read()
    cmds = set()
    for line in src.split("\n"):
        # Match: <var> = sub.add_parser("name"  or  p = sub.add_parser("name"
        m = re.match(r'\s+\w+ = sub\.add_parser\("(\w+)"', line)
        if m:
            cmds.add(m.group(1))
        m2 = re.match(r'\s+p = sub\.add_parser\("(\w+)"', line)
        if m2:
            cmds.add(m2.group(1))
    return cmds


def _get_documented_domains():
    """Get domain names from CLI-REFERENCE.md tables."""
    ref_path = os.path.join(REPO_ROOT, "docs", "CLI-REFERENCE.md")
    with open(ref_path) as f:
        content = f.read()
    domains = set()
    # Match: | `freq <domain>` or | `freq <domain> <action>`
    for m in re.finditer(r"`freq (\w+)", content):
        domains.add(m.group(1))
    return domains


class TestDocumentedDomainsExist(unittest.TestCase):
    """Every domain in CLI-REFERENCE.md must exist in cli.py."""

    def test_all_documented_domains_are_registered(self):
        """No phantom domains — every documented domain must be a real command."""
        cli_cmds = _get_cli_commands()
        doc_domains = _get_documented_domains()

        # Some documented "domains" are actually subcommands shown in examples
        # Filter to just the primary domain (first word after 'freq')
        phantoms = []
        for domain in doc_domains:
            if domain not in cli_cmds:
                # Check if it's a known non-command word in examples
                if domain in ("web01", "all", "pve01", "uptime",
                              "ssh", "ubuntu", "message"):
                    continue
                phantoms.append(domain)

        self.assertEqual(
            phantoms, [],
            f"CLI-REFERENCE lists domains that don't exist in cli.py: {phantoms}"
        )


class TestCriticalCommandsDocumented(unittest.TestCase):
    """Critical CLI commands must appear in CLI-REFERENCE.md."""

    CRITICAL = [
        "vm", "fleet", "host", "docker", "secure", "observe",
        "state", "auto", "ops", "hw", "store", "dr", "net",
        "serve", "init", "doctor", "help", "version", "demo",
    ]

    def test_critical_commands_in_reference(self):
        doc_domains = _get_documented_domains()
        missing = [c for c in self.CRITICAL if c not in doc_domains]
        self.assertEqual(missing, [],
                         f"Critical commands missing from CLI-REFERENCE: {missing}")


class TestCliReferenceConsistency(unittest.TestCase):
    """CLI-REFERENCE must be internally consistent."""

    def test_has_top_level_section(self):
        ref_path = os.path.join(REPO_ROOT, "docs", "CLI-REFERENCE.md")
        with open(ref_path) as f:
            content = f.read()
        self.assertIn("Top-Level", content)

    def test_has_core_domains_section(self):
        ref_path = os.path.join(REPO_ROOT, "docs", "CLI-REFERENCE.md")
        with open(ref_path) as f:
            content = f.read()
        self.assertIn("Core Domains", content)

    def test_defers_to_freq_help(self):
        """Doc must note that freq help is the live source of truth."""
        ref_path = os.path.join(REPO_ROOT, "docs", "CLI-REFERENCE.md")
        with open(ref_path) as f:
            content = f.read()
        self.assertIn("freq help", content)


if __name__ == "__main__":
    unittest.main()
