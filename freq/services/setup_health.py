"""Own setup completion markers and project honest init blockers."""

import datetime
import json
import os

from freq.core.config import load_toml


def setup_marker_exists(cfg):
    """True when setup or init has already crossed a completion boundary."""
    return any(
        os.path.isfile(path)
        for path in (
            os.path.join(cfg.data_dir, "setup-complete"),
            os.path.join(cfg.conf_dir, ".initialized"),
            os.path.join(cfg.conf_dir, ".web-setup-complete"),
        )
    )


def zero_state_setup_complete(cfg):
    """True only after both CLI init and browser handoff completed."""
    return os.path.isfile(os.path.join(cfg.conf_dir, ".initialized")) and os.path.isfile(
        os.path.join(cfg.conf_dir, ".web-setup-complete")
    )


def write_web_setup_markers(cfg):
    """Record that the browser setup path completed.

    This is intentionally separate from .initialized, which remains owned by
    freq init after successful fleet verification.
    """
    from freq import __version__

    os.makedirs(cfg.data_dir, exist_ok=True)
    marker = os.path.join(cfg.data_dir, "setup-complete")
    if not os.path.isfile(marker):
        with open(marker, "w") as f:
            f.write(f"Setup completed: {datetime.datetime.now().isoformat()}\n")

    os.makedirs(cfg.conf_dir, exist_ok=True)
    web_marker = os.path.join(cfg.conf_dir, ".web-setup-complete")
    if not os.path.isfile(web_marker):
        with open(web_marker, "w") as f:
            f.write(f"PVE FREQ {__version__} — web setup {datetime.datetime.now().isoformat()}\n")


def init_blocker_from_artifacts(cfg):
    """Return a truthful not-initialized reason from generated init artifacts."""
    status_path = os.path.join(cfg.conf_dir, "init-status.json")
    try:
        with open(status_path) as f:
            status = json.load(f)
    except (OSError, ValueError, TypeError):
        status = {}
    if isinstance(status, dict) and status:
        if status.get("initialized") is True:
            return ""
        raw_failed_checks = [
            str(item).strip()
            for item in status.get("failed_checks", []) or []
            if str(item).strip()
        ]
        failed_checks = [
            item
            for item in raw_failed_checks
            if "operator vm contract" not in str(item).lower()
            and "out-of-contract pve vm" not in str(item).lower()
        ]
        if failed_checks:
            return f"freq init ran and failed verification: {failed_checks[0]}"
        reason = str(status.get("reason") or "").strip()
        if (
            reason
            and "operator vm contract" not in reason.lower()
            and "out-of-contract pve vm" not in reason.lower()
        ):
            return f"freq init ran and failed verification: {reason}"
        if raw_failed_checks or reason:
            return ""

    fb_path = os.path.join(cfg.conf_dir, "fleet-boundaries.toml")
    inv_path = os.path.join(cfg.conf_dir, "pve-inventory.toml")
    fb_data = load_toml(fb_path)
    inv_data = load_toml(inv_path)
    if not fb_data and not inv_data:
        return ""

    if inv_data:
        return "freq init ran but did not mark initialized; run freq init --check for the failing check"
    return ""
