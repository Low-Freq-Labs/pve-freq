"""Watch-daemon process control below dashboard HTTP transport."""

import subprocess


def run_watch_action(action):
    """Run one watch-control action and project its process result."""
    result = subprocess.run(
        ["freq", "watch", action],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return {"ok": result.returncode == 0, "output": result.stdout}
