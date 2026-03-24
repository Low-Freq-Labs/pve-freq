"""NFS Security Policy.

Verify NFS mount options include safety flags:
- _netdev: don't mount before network is up
- nofail: don't block boot on mount failure
- soft,timeo=150,retrans=3: don't hang indefinitely

Missing these options causes boot hangs and filesystem freezes
when NFS servers are unreachable.
"""

POLICY = {
    "name": "nfs-security",
    "description": "Verify NFS mount options include safety flags",
    "scope": ["linux", "pve"],
    "resources": [
        {
            "type": "command_check",
            "path": "",
            "applies_to": ["linux", "pve"],
            "entries": {},
            "check_cmd": ("grep nfs /etc/fstab | grep -v '_netdev' | "
                          "grep -v '^#' || echo CLEAN"),
            "desired_output": "CLEAN",
            "fix_cmd": ("echo '# WARNING: NFS mounts should have "
                        "_netdev,nofail,soft,timeo=150,retrans=3' "
                        ">> /etc/fstab"),
            "after_change": {},
        },
    ],
}
