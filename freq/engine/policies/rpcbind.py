"""RPC bind security policy for FREQ.

Domain: freq state <check|fix|diff> (loaded by engine as individual policy)

Disables rpcbind on hosts that do not need NFS. PVE nodes are excluded because
rpcbind is required for HA/corosync cluster communication.

Replaces: Manual systemctl audits + CIS benchmark scripts

Architecture:
    - command_check type policy — uses systemctl to detect and disable
    - Scoped to linux and docker only (PVE intentionally excluded)

Design decisions:
    - Exclusion of PVE prevents breaking Proxmox HA clusters
    - Uses disable + stop to survive reboots
"""
POLICY = {
    "name": "rpcbind-disable",
    "description": "Disable rpcbind on hosts that don't need it",
    "scope": ["linux", "docker"],
    "resources": [
        {
            "type": "command_check",
            "applies_to": ["linux", "docker"],
            "key": "rpcbind",
            "check_cmd": "systemctl is-enabled rpcbind 2>/dev/null || echo 'not-found'",
            "entries": {
                "rpcbind": "disabled",
            },
            "fix_cmd": "systemctl stop rpcbind && systemctl disable rpcbind",
            "after_change": {},
        },
    ],
}
