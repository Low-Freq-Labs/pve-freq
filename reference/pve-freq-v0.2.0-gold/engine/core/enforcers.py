"""Generic enforcers — the hands of the engine.

Each enforcer type handles a specific kind of infrastructure resource:
- file_line: Key-value lines in config files (sshd_config, timesyncd.conf)
- middleware_config: TrueNAS middleware API calls (midclt)
- command_check: Verify by running a command and checking output
- package_ensure: Ensure a package is installed

Enforcers implement two methods:
- discover(host, resource, ssh) -> dict of current state
- fix(host, resource, finding, ssh) -> bool success
"""
import json
from engine.core.types import Host, Resource, Finding, CmdResult
from engine.core.transport import SSHTransport


class FileLineEnforcer:
    """Enforces key-value lines in config files.

    Handles: sshd_config, timesyncd.conf, daemon.json, etc.
    Pattern: KEY VALUE (space-separated) or KEY=VALUE (ini-style)
    """

    async def discover(self, host: Host, resource: Resource,
                       ssh: SSHTransport) -> dict:
        """Read config file and parse key-value pairs."""
        result = await ssh.execute(host, f"cat {resource.path}", sudo=True)
        if result.returncode != 0:
            return {"_error": f"Cannot read {resource.path}: {result.stderr}"}
        config = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                # Handle both "KEY VALUE" and "KEY=VALUE" formats
                if "=" in line and " " not in line.split("=")[0]:
                    parts = line.split("=", 1)
                else:
                    parts = line.split(None, 1)
                if len(parts) == 2:
                    config[parts[0]] = parts[1]
        return config

    async def fix(self, host: Host, resource: Resource,
                  finding: Finding, ssh: SSHTransport) -> bool:
        """Fix a single key-value entry in a config file.

        Strategy:
        1. If key exists (commented or active), sed-replace it
        2. If key doesn't exist at all, append it
        """
        key, value = finding.key, finding.desired
        path = resource.path

        # Check if key exists (active or commented)
        check = await ssh.execute(
            host, f"grep -c '^[#]*\\s*{key}' {path}", sudo=True
        )

        if check.stdout.strip() not in ("0", ""):
            # Key exists — replace it (handles both active and commented lines)
            # Escape forward slashes in value for sed
            safe_value = str(value).replace("/", "\\/")
            safe_key = str(key).replace("/", "\\/")
            cmd = f"sed -i 's/^[#]*\\s*{safe_key}.*/{safe_key} {safe_value}/' {path}"
        else:
            # Key doesn't exist — append
            cmd = f"echo '{key} {value}' >> {path}"

        result = await ssh.execute(host, cmd, sudo=True)
        return result.returncode == 0


class MiddlewareEnforcer:
    """Enforces config via TrueNAS middleware (midclt).

    The midclt CLI is TrueNAS's native configuration interface.
    It returns JSON and accepts JSON updates, making it ideal for
    declarative configuration management.
    """

    async def discover(self, host: Host, resource: Resource,
                       ssh: SSHTransport) -> dict:
        """Query TrueNAS middleware for current configuration."""
        method = resource.entries.get("_method", "ssh.config")
        result = await ssh.execute(
            host, f"midclt call {method}", sudo=True
        )
        if result.returncode != 0:
            return {"_error": f"midclt failed: {result.stderr}"}
        try:
            data = json.loads(result.stdout)
            # Flatten nested dicts for comparison
            if isinstance(data, dict):
                return data
            return {"_error": "Unexpected midclt response format"}
        except json.JSONDecodeError:
            return {"_error": f"Invalid JSON from midclt: {result.stdout[:100]}"}

    async def fix(self, host: Host, resource: Resource,
                  finding: Finding, ssh: SSHTransport) -> bool:
        """Apply configuration change via midclt update."""
        update_method = resource.entries.get("_update_method", "ssh.update")
        # Build the update payload
        if isinstance(finding.desired, bool):
            value = "true" if finding.desired else "false"
        elif isinstance(finding.desired, str):
            value = f'"{finding.desired}"'
        else:
            value = json.dumps(finding.desired)
        cmd = f'midclt call {update_method} \'{{"{ finding.key}": {value}}}\''
        result = await ssh.execute(host, cmd, sudo=True)
        return result.returncode == 0


class CommandCheckEnforcer:
    """Enforces by checking command output.

    Used for checks that don't map to a config file — like checking
    if a port is open, a service is running, or a rule exists.
    """

    async def discover(self, host: Host, resource: Resource,
                       ssh: SSHTransport) -> dict:
        """Run check command and capture output."""
        result = await ssh.execute(host, resource.check_cmd, sudo=True)
        return {
            "_cmd_output": result.stdout,
            "_cmd_rc": result.returncode,
            "_cmd_check": resource.check_cmd,
        }

    async def fix(self, host: Host, resource: Resource,
                  finding: Finding, ssh: SSHTransport) -> bool:
        """Apply the fix command."""
        if not resource.fix_cmd:
            return False
        result = await ssh.execute(host, resource.fix_cmd, sudo=True)
        return result.returncode == 0


class PackageEnforcer:
    """Ensures a package is installed.

    Currently supports Debian/Ubuntu (dpkg/apt). Platform-specific
    package managers can be added as needed.
    """

    async def discover(self, host: Host, resource: Resource,
                       ssh: SSHTransport) -> dict:
        """Check if package is installed."""
        pkg = resource.package
        result = await ssh.execute(
            host, f"dpkg -l {pkg} 2>/dev/null | grep -q '^ii' && echo installed || echo missing",
            sudo=True
        )
        status = result.stdout.strip()
        return {f"pkg_{pkg}": status if status in ("installed", "missing") else "unknown"}

    async def fix(self, host: Host, resource: Resource,
                  finding: Finding, ssh: SSHTransport) -> bool:
        """Install the missing package."""
        pkg = resource.package
        result = await ssh.execute(
            host,
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {pkg}",
            sudo=True,
        )
        return result.returncode == 0


# Enforcer registry — maps resource types to enforcer instances
_ENFORCERS = {
    "file_line": FileLineEnforcer(),
    "middleware_config": MiddlewareEnforcer(),
    "command_check": CommandCheckEnforcer(),
    "package_ensure": PackageEnforcer(),
}


def get_enforcer(resource_type: str):
    """Get the enforcer instance for a resource type.

    Returns None if the resource type is unknown.
    """
    return _ENFORCERS.get(resource_type)


def list_enforcers() -> list[str]:
    """List available enforcer types."""
    return list(_ENFORCERS.keys())
