"""Policy loader and executor.

Loads policies from engine/policies/*.py. Each policy module exports
a POLICY dict. The PolicyExecutor translates policies into discover/compare/fix
operations using generic enforcers.

Architecture:
- PolicyStore: discovers and loads all policy definitions
- PolicyExecutor: runs a policy's 5-phase lifecycle against a host
"""
import importlib
import os
import sys
from engine.core.types import Host, Policy, Resource, Finding, Severity
from engine.core.transport import SSHTransport
from engine.core import enforcers


class PolicyStore:
    """Discovers and loads all policies from the policies/ directory.

    Policies are Python modules that export a POLICY dict with:
    - name: str
    - description: str
    - scope: list[str] (host types)
    - resources: list[dict] (resource definitions)
    """

    def __init__(self, policies_dir: str = ""):
        self.policies: dict[str, Policy] = {}
        self._policies_dir = policies_dir
        if policies_dir:
            self._load_dir(policies_dir)

    def _load_dir(self, path: str):
        """Load all policy modules from a directory."""
        if not os.path.isdir(path):
            return

        # Add parent dir to sys.path so policies can be imported
        parent = os.path.dirname(path)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        for fname in sorted(os.listdir(path)):
            if fname.endswith(".py") and not fname.startswith("_"):
                mod_name = fname[:-3]
                try:
                    # Use the directory name as package
                    pkg_name = os.path.basename(path)
                    full_name = f"{pkg_name}.{mod_name}"
                    # Avoid re-importing
                    if full_name in sys.modules:
                        mod = sys.modules[full_name]
                    else:
                        mod = importlib.import_module(full_name)

                    if hasattr(mod, "POLICY"):
                        p = mod.POLICY
                        policy = Policy(
                            name=p["name"],
                            description=p["description"],
                            scope=p["scope"],
                            resources=[Resource(**r) for r in p["resources"]],
                        )
                        self.policies[policy.name] = policy
                except Exception as e:
                    print(f"  Warning: Failed to load policy {mod_name}: {e}",
                          file=sys.stderr)

    def get(self, name: str) -> Policy | None:
        """Get a policy by name."""
        return self.policies.get(name)

    def list_all(self) -> list[Policy]:
        """List all loaded policies."""
        return list(self.policies.values())

    def names(self) -> list[str]:
        """List all policy names."""
        return list(self.policies.keys())


class PolicyExecutor:
    """Executes a policy against a host using generic enforcers.

    Implements the 5-phase remediation arc:
    1. DISCOVER — read current state from host
    2. COMPARE — diff current vs desired
    3. FIX — apply changes
    4. ACTIVATE — restart services
    5. VERIFY — re-discover and confirm
    """

    def __init__(self, policy: Policy):
        self.policy = policy

    async def discover(self, host: Host, ssh: SSHTransport) -> dict:
        """Discover current state of all policy resources on host.

        Iterates over all resources in the policy, skipping those
        that don't apply to this host type. Returns merged state dict.
        """
        result = {}
        for resource in self.policy.resources:
            if host.htype not in resource.applies_to:
                continue
            enforcer = enforcers.get_enforcer(resource.type)
            if enforcer:
                partial = await enforcer.discover(host, resource, ssh)
                result.update(partial)
        if not result:
            result["_skip"] = True
        return result

    def desired_state(self, host: Host) -> dict:
        """Calculate desired state from policy resources.

        Handles platform-specific value resolution: if a value is a dict
        with platform keys, pick the one matching host.htype.
        """
        result = {}
        for resource in self.policy.resources:
            if host.htype not in resource.applies_to:
                continue
            for key, value in resource.entries.items():
                # Skip internal keys
                if key.startswith("_"):
                    continue
                # Platform-specific value resolution
                if isinstance(value, dict):
                    value = value.get(host.htype, value.get("default"))
                    if value is None:
                        continue
                result[key] = value
        return result

    def compare(self, host: Host) -> list[Finding]:
        """Compare current to desired, return findings.

        Each mismatch becomes a Finding with the key, current value,
        desired value, and severity.
        """
        findings = []
        for key, desired in host.desired.items():
            current = host.current.get(key)
            # Normalize for comparison (handle string/bool/int mismatches)
            if str(current).lower() != str(desired).lower():
                findings.append(Finding(
                    resource_type="config",
                    key=key,
                    current=current,
                    desired=desired,
                    severity=Severity.WARN,
                    platform=host.htype,
                ))
        return findings

    async def fix(self, host: Host, finding: Finding,
                  ssh: SSHTransport) -> bool:
        """Apply a fix for a single finding.

        Finds the resource that owns the finding key and delegates
        to the appropriate enforcer.
        """
        for resource in self.policy.resources:
            if host.htype not in resource.applies_to:
                continue
            # Check if this resource owns the finding key
            if finding.key in resource.entries:
                enforcer = enforcers.get_enforcer(resource.type)
                if enforcer:
                    return await enforcer.fix(host, resource, finding, ssh)
            # For command_check and package_ensure, match differently
            if resource.type == "command_check" and finding.key == "_cmd_output":
                enforcer = enforcers.get_enforcer(resource.type)
                if enforcer:
                    return await enforcer.fix(host, resource, finding, ssh)
            if resource.type == "package_ensure" and finding.key.startswith("pkg_"):
                enforcer = enforcers.get_enforcer(resource.type)
                if enforcer:
                    return await enforcer.fix(host, resource, finding, ssh)
        return False

    async def activate(self, host: Host, ssh: SSHTransport) -> bool:
        """Run after_change commands for all applicable resources.

        This is where services get restarted, configs get reloaded, etc.
        """
        for resource in self.policy.resources:
            if host.htype not in resource.applies_to:
                continue
            after_cmd = resource.after_change.get(host.htype, "")
            if after_cmd:
                result = await ssh.execute(host, after_cmd, sudo=True)
                if result.returncode != 0:
                    return False
        return True

    async def verify(self, host: Host, ssh: SSHTransport) -> bool:
        """Re-discover and compare to desired. True if compliant.

        This is the proof that the fix actually worked. We re-read
        the live state and compare against what we wanted.
        """
        new_state = await self.discover(host, ssh)
        if new_state.get("_skip") or new_state.get("_error"):
            return False
        for key, desired in host.desired.items():
            current = new_state.get(key)
            if str(current).lower() != str(desired).lower():
                return False
        return True
