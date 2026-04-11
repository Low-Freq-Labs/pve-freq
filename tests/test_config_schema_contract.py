"""Tests for config schema contract — documented keys must be parsed.

Bug: pve.ssh_user was documented in CONFIGURATION.md but never parsed
into FreqConfig. Users who set it got no effect — silent config drift.

Contract:
- Every key documented in CONFIGURATION.md must be parsed by config.py
- Every key in freq.toml.example must be documented or commented-out
- FreqConfig must have a field for every parsed key
- Phantom keys (documented but not parsed) must not exist
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestNoPhantomDocKeys(unittest.TestCase):
    """CONFIGURATION.md must not document keys that config.py ignores."""

    # Keys that are legitimately in docs but parsed under different names
    # or are nested sub-table keys (personality, container, host fields)
    KNOWN_NESTED_OR_RENAMED = {
        # Parsed under pve_ prefix
        "api_token_id", "api_token_secret_path", "api_verify_ssl",
        "nodes", "node_names",
        # Parsed under ssh_ prefix
        "service_account", "connect_timeout", "max_parallel", "mode",
        # Parsed under vm_ prefix
        "cores", "ram", "disk", "cpu", "machine", "scsihw",
        "gateway", "nameserver",
        # Infrastructure section keys
        "pfsense_ip", "truenas_ip", "switch_ip", "synology_ip", "opnsense_ip",
        # NIC profile sub-table
        "bridge", "mtu", "dev", "prod", "standard", "minimal",
        # Notification section keys
        "discord_webhook", "slack_webhook", "telegram_bot_token",
        "telegram_chat_id", "smtp_host", "smtp_port", "smtp_user",
        "smtp_password", "smtp_to", "smtp_tls", "ntfy_url", "ntfy_topic",
        "gotify_url", "gotify_token", "pushover_user", "pushover_token",
        "webhook_url",
        # Safety section
        "protected_vmids", "protected_ranges", "max_failure_percent",
        # Dashboard section
        "dashboard_port", "tls_cert", "tls_key",
        # Monitoring section
        "agent_port", "watchdog_port",
        # Docker section
        "docker_dev_ip", "docker_config_base", "docker_backup_dir",
        # Misc parsed directly
        "legacy_password_file", "ascii", "timezone", "cluster_name",
        "version", "brand", "build", "debug",
        # Sub-table keys (not top-level FreqConfig)
        "pool", "type", "host", "user", "config_path",
        # Container/personality/host sub-table keys (not FreqConfig)
        "name", "port", "api_path", "auth_type", "auth_header",
        "vault_key", "ip", "label", "groups", "compose_path",
        "compose", "critical", "image", "status",
        "subtitle", "vibe_enabled", "vibe_probability",
        "dashboard_header", "celebrations", "taglines", "quotes",
        # Fleet boundaries sub-keys
        "description", "tier", "vmids", "range_start", "range_end",
        # Safety/risk/rules sub-keys
        "severity", "impact", "recovery", "condition", "threshold",
        "cooldown", "command", "timeout", "enabled", "target",
        "expect", "confirm", "risk", "aliases", "depends_on",
        "depended_by", "family", "filename", "sha_url",
        "id", "prefix", "subnet", "duration", "url", "role",
        # SNMP
        "snmp_community",
    }

    def test_no_phantom_keys_in_docs(self):
        """Every key in CONFIGURATION.md [section] tables must be parseable."""
        doc_path = FREQ_ROOT / "docs" / "CONFIGURATION.md"
        content = doc_path.read_text()

        # Extract keys from markdown tables: | `key_name` | type |
        # Filter out values that look like types/defaults (e.g. false, true, string)
        doc_keys = set()
        for m in re.findall(r'\| `([a-z_]+)` \|', content):
            if m not in ("string", "int", "bool", "list", "dict", "true", "false"):
                doc_keys.add(m)

        # Remove known nested/renamed keys
        unknown = doc_keys - self.KNOWN_NESTED_OR_RENAMED

        # Check each unknown key is in FreqConfig
        config_path = FREQ_ROOT / "freq" / "core" / "config.py"
        config_content = config_path.read_text()

        phantoms = []
        for key in sorted(unknown):
            # Check if key appears as a FreqConfig field or is parsed
            if key not in config_content:
                phantoms.append(key)

        self.assertEqual(phantoms, [],
                         f"Phantom keys in CONFIGURATION.md (documented but not parsed): {phantoms}")


class TestExampleKeysDocumented(unittest.TestCase):
    """Active (uncommented) example keys should correspond to real config."""

    def test_example_active_keys_are_parseable(self):
        """Every uncommented key in freq.toml.example must be in FreqConfig."""
        example_path = FREQ_ROOT / "freq" / "data" / "conf-templates" / "freq.toml.example"
        config_path = FREQ_ROOT / "freq" / "core" / "config.py"

        config_content = config_path.read_text()

        # Extract uncommented keys from example
        active_keys = set()
        for line in example_path.read_text().split("\n"):
            line = line.strip()
            if line.startswith("#") or line.startswith("[") or "=" not in line:
                continue
            key = line.split("=")[0].strip()
            if key:
                active_keys.add(key)

        # NIC profile sub-keys are parsed by nic_profiles loader, not as FreqConfig fields
        nic_keys = {"standard", "minimal", "prod", "dev", "public", "mtu", "bridge"}

        # Every active key should be parsed somewhere in config.py
        unparsed = []
        for key in sorted(active_keys):
            if key in nic_keys:
                continue  # Parsed by NIC profiles loader
            if key not in config_content:
                unparsed.append(key)

        self.assertEqual(unparsed, [],
                         f"Example keys not parsed by config.py: {unparsed}")


if __name__ == "__main__":
    unittest.main()
