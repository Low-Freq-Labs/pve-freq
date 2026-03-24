"""RPC bind security policy.

Disables rpcbind on hosts that don't need NFS.
PVE nodes keep rpcbind for HA/corosync.
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
