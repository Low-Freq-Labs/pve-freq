"""NTP Synchronization Policy.

Ensures all Linux hosts use consistent NTP servers via systemd-timesyncd.
Fleet time sync is critical for log correlation and certificate validation.
"""

POLICY = {
    "name": "ntp-sync",
    "description": "Ensure NTP is configured for fleet time synchronization",
    "scope": ["linux"],
    "resources": [
        {
            "type": "file_line",
            "path": "/etc/systemd/timesyncd.conf",
            "applies_to": ["linux"],
            "entries": {
                "NTP": "2.debian.pool.ntp.org",
                "FallbackNTP": "ntp.ubuntu.com",
            },
            "after_change": {
                "linux": "systemctl restart systemd-timesyncd",
            },
        },
    ],
}
