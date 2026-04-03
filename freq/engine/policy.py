"""Declarative policy executor for FREQ.

Domain: freq state <check|fix|diff>

Evaluates declarative policy dicts against live host state. A 25-line policy
dict replaces 200 lines of bash — discover, compare, fix, activate, verify.

Replaces: Ansible playbooks + Chef InSpec ($50k+/yr enterprise)

Architecture:
    - PolicyExecutor runs one policy against one host (6-phase pipeline)
    - PolicyStore is the in-memory registry of all loaded policy dicts

Design decisions:
    - Policies are dicts, not classes — keeps them human-editable TOML
    - Platform-aware overrides via nested dicts in entries
"""
import difflib

from freq.core.types import Finding, Severity


def _escape_sed(text):
    """Escape regex metacharacters for safe use in sed patterns."""
    for ch in r'\.^$*+?{}[]|()':
        text = text.replace(ch, '\\' + ch)
    return text


class PolicyExecutor:
    """Executes a single policy against a host."""

    def __init__(self, policy: dict):
        if "name" not in policy:
            raise ValueError("Policy missing required 'name' key")
        self.policy = policy
        self.name = policy["name"]
        self.scope = policy.get("scope", [])

    def applies_to(self, host) -> bool:
        """Check if this policy applies to a host type."""
        return host.htype.lower() in [s.lower() for s in self.scope]

    def applicable_resources(self, host) -> list:
        """Get resources that apply to this host type."""
        result = []
        for res in self.policy.get("resources", []):
            applies = res.get("applies_to", self.scope)
            if host.htype.lower() in [a.lower() for a in applies]:
                result.append(res)
        return result

    def desired_state(self, host) -> dict:
        """Build the desired state dict for a host, resolving platform overrides."""
        desired = {}
        for res in self.applicable_resources(host):
            for key, value in res.get("entries", {}).items():
                if key.startswith("_"):
                    continue  # Skip metadata keys
                if isinstance(value, dict):
                    # Platform-specific value
                    desired[key] = value.get(host.htype, value.get("default", ""))
                else:
                    desired[key] = value
        return desired

    def compare(self, current: dict, desired: dict) -> list:
        """Compare current vs desired state, return list of Findings."""
        findings = []
        for key, want in desired.items():
            got = current.get(key)
            # Normalize for comparison
            want_str = str(want).strip()
            got_str = str(got).strip() if got is not None else ""

            if got_str != want_str:
                findings.append(Finding(
                    resource_type="config",
                    key=key,
                    current=got_str or "(not set)",
                    desired=want_str,
                    severity=Severity.WARN,
                ))
        return findings

    def diff_text(self, current: dict, desired: dict) -> str:
        """Generate a git-style diff between current and desired state."""
        current_lines = [f"{k} = {v}" for k, v in sorted(current.items())]
        desired_lines = [f"{k} = {v}" for k, v in sorted(desired.items())]

        diff = difflib.unified_diff(
            current_lines, desired_lines,
            fromfile="current", tofile="desired",
            lineterm="",
        )
        return "\n".join(diff)

    def fix_commands(self, host, findings: list) -> list:
        """Generate fix commands for findings."""
        commands = []
        for res in self.applicable_resources(host):
            res_type = res.get("type", "")
            path = res.get("path", "")

            for finding in findings:
                key = finding.key
                desired = finding.desired

                if res_type == "file_line" and path:
                    # sed command to update or append
                    escaped_key = _escape_sed(key)
                    escaped_desired = desired.replace("/", "\\/")
                    commands.append(
                        f"grep -q '^{escaped_key}' {path} && "
                        f"sed -i 's/^{escaped_key}.*/{key} {escaped_desired}/' {path} || "
                        f"echo '{key} {escaped_desired}' >> {path}"
                    )
                elif res_type == "command_check":
                    fix_cmd = res.get("fix_cmd", "")
                    if fix_cmd:
                        commands.append(fix_cmd)

        return commands

    def activate_commands(self, host) -> list:
        """Get after_change commands for this host type."""
        commands = []
        for res in self.applicable_resources(host):
            after = res.get("after_change", {})
            cmd = after.get(host.htype, after.get("default", ""))
            if cmd:
                commands.append(cmd)
        return commands


class PolicyStore:
    """Registry of all available policies."""

    def __init__(self):
        self.policies = {}

    def register(self, policy: dict):
        """Register a policy dict."""
        name = policy["name"]
        self.policies[name] = policy

    def get(self, name: str) -> dict:
        """Get a policy by name."""
        return self.policies.get(name)

    def list(self) -> list:
        """List all registered policies."""
        return list(self.policies.values())

    def for_host(self, host) -> list:
        """Get all policies that apply to a host type."""
        result = []
        for p in self.policies.values():
            scope = p.get("scope", [])
            if host.htype.lower() in [s.lower() for s in scope]:
                result.append(p)
        return result
