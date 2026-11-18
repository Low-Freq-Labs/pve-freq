"""Transition Web Init from the setup listener to the managed service."""

import os
import shlex
import subprocess
import sys

from freq.core import log as logger

_SETUP_ACCOUNT = "pve-freq-setup"
_SETUP_SUDOERS = "/etc/sudoers.d/pve-freq-setup"


def schedule_setup_runtime_handoff(cfg):
    """Move Web Init from the bootstrap listener to the managed service.

    Web-launched init runs inside a temporary setup listener so the browser can
    stream progress before the managed service account exists. Once init has
    created freq-serve.service, that bootstrap process must get out of the way
    or it will keep old config cached and compete with the real dashboard.
    """
    try:
        has_service = subprocess.run(
            ["systemctl", "cat", "freq-serve.service"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        has_service = False
    if not has_service:
        return False

    current_pid = os.getpid()
    current_user = ""
    try:
        import pwd

        current_user = pwd.getpwuid(os.geteuid()).pw_name
    except Exception:
        current_user = ""
    if current_user and current_user == getattr(cfg, "ssh_service_account", ""):
        return False

    prefix = []
    if os.geteuid() != 0:
        prefix = ["sudo", "-n"]
    setup_unit = "/etc/systemd/system/pve-freq-setup.service"
    bootstrap_tls_dir = os.path.join(cfg.install_dir, "tls", "bootstrap")
    finalize_code = (
        "from freq.core.config import load_config; "
        "from freq.modules.init_cmd import _finalize_web_init_runtime_ownership; "
        "cfg=load_config(force=True); "
        "raise SystemExit(0 if _finalize_web_init_runtime_ownership("
        "cfg, cfg.ssh_service_account) else 1)"
    )
    finalize_cmd = prefix + [
        "env",
        f"FREQ_DIR={cfg.install_dir}",
        f"PYTHONPATH={cfg.install_dir}",
        sys.executable,
        "-c",
        finalize_code,
    ]
    prepare_switch = (
        " ".join(shlex.quote(part) for part in finalize_cmd)
        + " && "
        + " ".join(
            shlex.quote(part)
            for part in prefix + ["systemctl", "disable", "--now", "pve-freq-setup.service"]
        )
        + " >/dev/null 2>&1 && "
        + " ".join(shlex.quote(part) for part in prefix + ["rm", "-f", setup_unit])
        + " && "
        + " ".join(shlex.quote(part) for part in prefix + ["rm", "-rf", bootstrap_tls_dir])
        + " && "
        + " ".join(shlex.quote(part) for part in prefix + ["systemctl", "daemon-reload"])
        + " >/dev/null 2>&1"
    )
    start_managed = (
        "sleep 2; "
        + " ".join(shlex.quote(part) for part in prefix + ["systemctl", "restart", "freq-serve.service"])
        + " >/dev/null 2>&1 || "
        + " ".join(shlex.quote(part) for part in prefix + ["systemctl", "start", "freq-serve.service"])
        + " >/dev/null 2>&1"
    )
    retire_setup_identity = " ".join(
        shlex.quote(part)
        for part in prefix
        + [
            "/bin/sh",
            "-c",
            f"rm -f {_SETUP_SUDOERS}; userdel -r {_SETUP_ACCOUNT} >/dev/null 2>&1 || true",
        ]
    )
    script = (
        f"if {prepare_switch}; then if {start_managed}; then "
        f"{retire_setup_identity}; else exit 1; fi; else exit 1; fi"
    )
    run_cmd = prefix + [
        "systemd-run",
        "--quiet",
        "--collect",
        "--unit=pve-freq-web-init-handoff",
        "--on-active=5",
        "/bin/sh",
        "-c",
        script,
    ]
    # This parent's epoch is not shared with the mutating Python child. Refuse
    # its future reads before either launch path, even if scheduling later fails.
    # The fence is not a shared-generation or other-process exclusion mechanism.
    from freq.core.read_source_epoch import retire_process_reads, SourceWriteUnavailable
    try:
        retire_process_reads()
    except SourceWriteUnavailable:
        return False  # No mutating launcher or fallback while a reader is active.

    try:
        scheduled = subprocess.run(
            run_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).returncode == 0
        if scheduled:
            logger.info("setup_runtime_handoff_scheduled", pid=current_pid, method="systemd-run")
            return True
    except (OSError, subprocess.SubprocessError):
        pass

    fallback_script = "sleep 5; " + script
    try:
        subprocess.Popen(
            ["/bin/sh", "-c", fallback_script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("setup_runtime_handoff_scheduled", pid=current_pid, method="detached-shell")
        return True
    except OSError as e:
        logger.warn(f"setup runtime handoff scheduling failed: {e}")
        return False
