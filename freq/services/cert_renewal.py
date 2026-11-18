"""Managed certificate-renewal scheduling below dashboard transport."""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import threading
import time

from freq.core import log as logger


def managed_cert_renewal_enabled(cfg) -> bool:
    """Return whether FREQ owns renewal for one complete managed certificate."""
    certs = getattr(cfg, "certificates", {}) or {}
    if not isinstance(certs, dict):
        return False
    if (
        str(certs.get("management_mode") or "managed").strip().lower()
        == "adopted_existing"
    ):
        return False
    if str(certs.get("renewal_owner") or "").strip().lower() == "external":
        return False
    return bool(
        certs.get("base_domain")
        and certs.get("dns_provider")
        and certs.get("dns_token_path")
    )


def start_cert_renewal_scheduler_if_needed(cfg, shutdown_flag) -> None:
    """Run managed ACME renew and deploy daily in container or no-cron installs."""
    if not managed_cert_renewal_enabled(cfg):
        return
    state_dir = os.path.join(cfg.data_dir, "certs")
    state_path = os.path.join(state_dir, "renewal-scheduler.json")

    def read_state():
        try:
            with open(state_path) as state_file:
                return json.load(state_file)
        except Exception:
            return {}

    def write_state(data):
        try:
            os.makedirs(state_dir, mode=0o700, exist_ok=True)
            with open(state_path, "w") as state_file:
                json.dump(data, state_file, indent=2)
        except OSError as error:
            logger.warning(f"cert_renewal_scheduler_state_write_failed: {error}")

    def run_scheduler():
        # Let the dashboard finish startup and cache warmup before network ACME.
        time.sleep(300)
        while not shutdown_flag.is_set():
            today = datetime.date.today().isoformat()
            state = read_state()
            if state.get("last_attempt_day") != today:
                command = [
                    sys.executable,
                    "-m",
                    "freq",
                    "--yes",
                    "cert",
                    "renew",
                    "--deploy",
                ]
                started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                logger.info(
                    "cert_renewal_scheduler_start",
                    command="python -m freq --yes cert renew --deploy",
                )
                try:
                    # Retire only when the existing daily child is about to run.
                    from freq.core.read_source_epoch import retire_process_reads
                    retire_process_reads()
                    result = subprocess.run(
                        command,
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        timeout=1800,
                    )
                    write_state(
                        {
                            "last_attempt_day": today,
                            "last_attempt_at": started,
                            "last_returncode": result.returncode,
                            "last_stdout_tail": (result.stdout or "")[-2000:],
                            "last_stderr_tail": (result.stderr or "")[-2000:],
                        }
                    )
                    if result.returncode == 0:
                        logger.info(
                            "cert_renewal_scheduler_ok",
                            returncode=result.returncode,
                        )
                    else:
                        logger.warning(
                            f"cert_renewal_scheduler_failed: rc={result.returncode}"
                        )
                except MemoryError:
                    raise
                except Exception as error:
                    write_state(
                        {
                            "last_attempt_day": today,
                            "last_attempt_at": started,
                            "last_returncode": -1,
                            "last_error": str(error),
                        }
                    )
                    logger.warning(f"cert_renewal_scheduler_error: {error}")
            shutdown_flag.wait(3600)

    threading.Thread(
        target=run_scheduler,
        daemon=True,
        name="freq-cert-renewal",
    ).start()
    logger.info("cert_renewal_scheduler_started")
