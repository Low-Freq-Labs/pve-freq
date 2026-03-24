"""Auto-Updates Policy.

Deploy unattended-upgrades for automatic security patching on
Debian/Ubuntu hosts and PVE nodes. Critical for keeping the fleet
patched without manual intervention.
"""

POLICY = {
    "name": "auto-updates",
    "description": "Deploy unattended-upgrades for automatic security patching",
    "scope": ["linux", "pve"],
    "resources": [
        {
            "type": "package_ensure",
            "path": "",
            "applies_to": ["linux", "pve"],
            "entries": {},
            "package": "unattended-upgrades",
            "after_change": {
                "linux": "dpkg-reconfigure -plow unattended-upgrades",
                "pve": "dpkg-reconfigure -plow unattended-upgrades",
            },
        },
    ],
}
