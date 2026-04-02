"""SSH hardening policy for FREQ.

Domain: freq state <check|fix|diff> (loaded by engine as individual policy)

Enforces secure sshd_config across all fleet host types. Platform-aware: PVE
gets MaxAuthTries=5 for cluster auth, Linux/Docker get MaxAuthTries=3.

Replaces: CIS Benchmark SSH audit scripts + manual sshd_config management

Architecture:
    - file_line type policy — sed-based in-place edits to sshd_config
    - Platform overrides via nested dicts (PVE vs Linux vs Docker)
    - after_change restarts sshd to apply immediately

Design decisions:
    - PVE MaxAuthTries=5 prevents cluster join failures
    - PermitRootLogin=prohibit-password allows key-only root (PVE requirement)
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
                "linux": "systemctl restart sshd 2>/dev/null || systemctl restart ssh 2>/dev/null",
                "pve": "systemctl restart sshd 2>/dev/null || systemctl restart ssh 2>/dev/null",
                "docker": "systemctl restart sshd 2>/dev/null || systemctl restart ssh 2>/dev/null",
            },
        },
    ],
}
