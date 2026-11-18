"""Shared serialization and pacing for live iDRAC SSH sessions."""

import subprocess
import threading
import time

IDRAC_SESSION_LOCK = threading.Lock()
IDRAC_SESSION_GAP_SECONDS = 2.0
_idrac_last_session_at = 0.0


def _run_idrac_session(operation, gap_seconds=IDRAC_SESSION_GAP_SECONDS):
    """Run one operation under the shared iDRAC lock and pacing window."""
    global _idrac_last_session_at
    with IDRAC_SESSION_LOCK:
        since = time.monotonic() - _idrac_last_session_at
        if since < gap_seconds:
            time.sleep(gap_seconds - since)
        result = operation()
        _idrac_last_session_at = time.monotonic()
        return result


def _run_idrac_subprocess(cmd, timeout):
    """Serialize an iDRAC subprocess read through the shared session gate."""
    return _run_idrac_session(
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    )
