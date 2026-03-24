"""SSH hardening policy.

Enforces secure SSH configuration across fleet.
Platform-aware: PVE needs different MaxAuthTries for cluster operations.
"""
POLICY = {
    "name": "ssh-hardening",
    "description": "Harden SSH daemon configuration across fleet",
    "scope": ["linux", "pve", "docker"],
    "resources": [
        {
            "type": "file_line",
            "path": "/etc/ssh/sshd_config",
            "applies_to": ["linux", "pve", "docker"],
            "entries": {
                "PermitRootLogin": {
                    "linux": "prohibit-password",
                    "pve": "prohibit-password",
                    "docker": "prohibit-password",
                },
                "PasswordAuthentication": "no",
                "MaxAuthTries": {
                    "linux": "3",
                    "pve": "5",  # PVE cluster needs more auth attempts
                    "docker": "3",
                },
                "X11Forwarding": "no",
                "PermitEmptyPasswords": "no",
                "ClientAliveInterval": "300",
                "ClientAliveCountMax": "2",
            },
            "after_change": {
                "linux": "systemctl restart sshd",
                "pve": "systemctl restart sshd",
                "docker": "systemctl restart sshd",
            },
        },
    ],
}
