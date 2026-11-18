"""NTP time synchronization policy for FREQ.

Domain: freq state <check|fix|diff> (loaded by engine as individual policy)

Ensures all fleet hosts use consistent NTP servers. Targets systemd-timesyncd
on Linux and Docker hosts, restarts the service after any change.

Replaces: Manual NTP audits + Ansible ntp role

Architecture:
    - Pure data dict consumed by PolicyExecutor — no executable code
    - Scoped to linux and docker host types (PVE uses chrony separately)

Design decisions:
    - Declarative dict, not a class — human-editable, testable as data
    - after_change restarts timesyncd to apply immediately
"""

POLICY = {
    "name": "ntp-sync",
    "description": "Ensure consistent NTP time synchronization",
    "scope": ["linux", "pve", "docker"],
    "resources": [
        {
            "type": "file_line",
            "path": "/etc/systemd/timesyncd.conf",
            "applies_to": ["linux", "docker"],
            "entries": {
                "NTP": "pool.ntp.org",
                "FallbackNTP": "time.cloudflare.com",
            },
            "after_change": {
                "linux": "systemctl restart systemd-timesyncd",
                "docker": "systemctl restart systemd-timesyncd",
            },
        },
    ],
}
