"""Bounded SSH ControlMaster cleanup below dashboard lifecycle transport."""

import concurrent.futures
import glob
import os
import signal
import subprocess
import time

from freq.core import log as logger


def cleanup_ssh_mux(cfg):
    """Kill SSH ControlMaster mux sockets within a hard shutdown budget."""
    svc_name = cfg.ssh_service_account
    mux_dir = os.path.expanduser(f"~{svc_name}/.ssh/freq-mux")
    if not os.path.isdir(mux_dir):
        return
    mux_sockets = glob.glob(os.path.join(mux_dir, "*"))
    if not mux_sockets:
        return

    def _exit_one(sock):
        try:
            proc = subprocess.Popen(
                ["ssh", "-O", "exit", "-o", f"ControlPath={sock}", "dummy"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    try:
                        proc.kill()
                    except Exception:
                        pass
                try:
                    proc.communicate(timeout=1)
                except Exception:
                    pass
        except Exception:
            pass

    budget = 8
    started = time.monotonic()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(mux_sockets))) as pool:
            futures = [pool.submit(_exit_one, sock) for sock in mux_sockets]
            for future in concurrent.futures.as_completed(futures, timeout=budget):
                try:
                    future.result(timeout=0.1)
                except Exception:
                    pass
    except concurrent.futures.TimeoutError:
        logger.warning(
            f"ssh_mux cleanup exceeded {budget}s budget — leaving stragglers to systemd",
            elapsed=round(time.monotonic() - started, 1),
            sockets=len(mux_sockets),
        )
