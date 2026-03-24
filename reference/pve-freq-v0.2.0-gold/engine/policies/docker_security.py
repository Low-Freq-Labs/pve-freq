"""Docker Security Policy.

Enforces Docker daemon configuration best practices:
- JSON log driver with rotation (prevent disk fill)
- Max log size and file count

Note: daemon.json is a JSON file, but we treat it with file_line
enforcer for simplicity. For production, a JSON-aware enforcer
could be added.
"""

POLICY = {
    "name": "docker-security",
    "description": "Docker security: log rotation, daemon hardening",
    "scope": ["linux"],
    "resources": [
        {
            "type": "file_line",
            "path": "/etc/docker/daemon.json",
            "applies_to": ["linux"],
            "entries": {
                '"log-driver"': '"json-file"',
                '"log-opts"': '{"max-size": "10m", "max-file": "3"}',
            },
            "after_change": {
                "linux": "systemctl restart docker",
            },
        },
    ],
}
