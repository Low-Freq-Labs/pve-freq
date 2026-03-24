"""SSH Hardening Policy — the reference policy that proves the architecture.

Covers:
- PermitRootLogin: prohibit-password on linux/pve/pfsense
- MaxAuthTries: 3 on linux/pfsense, 5 on PVE (cluster needs)
- X11Forwarding: no everywhere
- AllowTcpForwarding: no everywhere
- TrueNAS: rootlogin=false, tcpfwd=false via middleware

Platform-aware: PVE keeps prohibit-password (required for cluster SSH).
TrueNAS uses midclt instead of sshd_config.
"""

POLICY = {
    "name": "ssh-hardening",
    "description": "Harden SSH configuration across fleet "
                   "(PermitRootLogin, MaxAuthTries, X11Forwarding)",
    "scope": ["linux", "pve", "truenas", "pfsense"],
    "resources": [
        {
            "type": "file_line",
            "path": "/etc/ssh/sshd_config",
            "applies_to": ["linux", "pve", "pfsense"],
            "entries": {
                "PermitRootLogin": {
                    "linux": "prohibit-password",
                    "pve": "prohibit-password",
                    "pfsense": "prohibit-password",
                },
                "MaxAuthTries": {
                    "linux": "3",
                    "pve": "5",
                    "pfsense": "3",
                },
                "X11Forwarding": "no",
                "AllowTcpForwarding": "no",
            },
            "after_change": {
                "linux": "systemctl restart sshd",
                "pve": "systemctl restart sshd",
                "pfsense": "/etc/rc.d/sshd restart",
            },
        },
        {
            "type": "middleware_config",
            "path": "",
            "applies_to": ["truenas"],
            "entries": {
                "_method": "ssh.config",
                "_update_method": "ssh.update",
                "rootlogin": False,
                "tcpfwd": False,
            },
            "after_change": {
                "truenas": "midclt call service.restart ssh",
            },
        },
    ],
}
