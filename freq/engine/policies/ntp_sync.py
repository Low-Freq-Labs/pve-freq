"""NTP time synchronization policy.

Ensures all hosts use consistent NTP servers for clock sync.
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
                "NTP": "2.debian.pool.ntp.org",
                "FallbackNTP": "ntp.ubuntu.com",
            },
            "after_change": {
                "linux": "systemctl restart systemd-timesyncd",
                "docker": "systemctl restart systemd-timesyncd",
            },
        },
    ],
}
