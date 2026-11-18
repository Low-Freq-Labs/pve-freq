#!/usr/bin/env python3
"""Run the real freq dashboard against deterministic, temporary test state."""

from __future__ import annotations

import argparse
import json
import os
import signal
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path

from freq.api import auth, terminal
from freq.core import setup_discovery
from freq.core.config import FreqConfig
from freq.core.setup_contract import contract_path, credential_vault_key, load_setup_contract
from freq.core.setup_state import load_setup_state, setup_state_path
from freq.modules import serve, users
from freq.modules.vault import vault_list

TEST_USER = "admin"
TEST_OPERATOR = "operator"
TEST_PASSWORD = "hermetic-dashboard-password"
ZERO_STATE_SECRETS = (
    "operator-password",
    "bootstrap-password",
    "device-password",
    "service-password",
)


def _prepare_hermetic_first_admin_claim(cfg: FreqConfig, root: Path) -> tuple[dict, Path]:
    """Deliver the real generated claim once through a private tests-only sink."""
    from freq.core import first_admin_claim

    delivery_path = root / "first-admin-claim.delivery"

    def deliver(_claim_id: str, secret: str, _generated_at: float) -> None:
        fd = os.open(
            delivery_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", closefd=False) as stream:
                stream.write(secret)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
        if stat.S_IMODE(delivery_path.stat().st_mode) != 0o600:
            raise AssertionError("first-admin claim delivery adapter is not 0600")

    metadata = first_admin_claim.prepare_first_admin_claim(
        cfg,
        users_present=False,
        setup_complete=False,
        deliver=deliver,
        warn=lambda _message: None,
    )
    if metadata.get("state") != "available" or not delivery_path.is_file():
        raise AssertionError("first-admin claim did not reach the private delivery sink")
    return metadata, delivery_path


def _config(root: Path) -> FreqConfig:
    cfg = FreqConfig()
    cfg.install_dir = str(root / "install")
    cfg.conf_dir = str(root / "conf")
    cfg.data_dir = str(root / "data")
    cfg.cache_dir = str(root / "cache")
    cfg.log_file = str(root / "data" / "log" / "freq.log")
    cfg.hosts_file = str(root / "conf" / "hosts.toml")
    cfg.key_dir = str(root / "keys")
    cfg.credentials_dir = str(root / "credentials")
    cfg.vault_dir = str(root / "vault")
    cfg.vault_file = str(root / "vault" / "vault.enc")
    cfg.ssh_key_path = str(root / "keys" / "freq_id_ed25519")
    cfg.ssh_rsa_key_path = str(root / "keys" / "freq_id_rsa")
    cfg.ssh_service_account = "freq-admin"
    cfg.hosts = []
    cfg.pve_nodes = []
    for path in (
        cfg.install_dir,
        cfg.conf_dir,
        cfg.data_dir,
        cfg.cache_dir,
        cfg.key_dir,
        cfg.credentials_dir,
        cfg.vault_dir,
    ):
        Path(path).mkdir(parents=True, exist_ok=True)
    return cfg


def _hermetic_terminal_child_command() -> list[str]:
    """Return a local PTY child while leaving terminal product code real."""
    child = (
        "import signal, sys\n"
        "signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))\n"
        "for line in sys.stdin:\n"
        "    if 'export PS1=' in line:\n"
        "        continue\n"
        "    sys.stdout.write('HERMETIC TERMINAL OUTPUT\\r\\n')\n"
        "    sys.stdout.flush()\n"
    )
    return [sys.executable, "-u", "-c", child]


def _install_fixture(cfg: FreqConfig) -> None:
    """Bind product seams to hermetic state while preserving real HTTP code."""
    serve.load_config = lambda *args, **kwargs: cfg
    auth.load_config = lambda *args, **kwargs: cfg
    terminal.load_config = lambda *args, **kwargs: cfg
    terminal._build_ssh_cmd = lambda **kwargs: _hermetic_terminal_child_command()
    serve._is_first_run = lambda: False
    users._load_users = lambda loaded_cfg: [
        {"username": TEST_USER, "role": "admin"},
        {"username": TEST_OPERATOR, "role": "operator"},
    ]
    auth.vault_get = lambda loaded_cfg, namespace, key: "hermetic-password-hash"
    auth.verify_password = lambda password, stored: password == TEST_PASSWORD
    auth.check_rate_limit = lambda *args, **kwargs: True
    auth.record_login_attempt = lambda *args, **kwargs: None

    now = time.time()
    serve._bg_cache["fleet_overview"] = {
        "vms": [],
        "vm_nics": {},
        "physical": [],
        "pve_nodes": [
            {
                "name": "pve-hermetic",
                "ip": "192.0.2.10",
                "online": True,
                "state": "live",
            }
        ],
        "vlans": [],
        "nic_profiles": {},
        "categories": {},
        "summary": {"resource_count": 1, "running": 1, "stopped": 0},
        "fleet_state": "live",
        "fleet_reason": "hermetic fixture healthy",
    }
    serve._bg_cache["health"] = {
        "hosts": [
            {
                "label": "pve-hermetic",
                "ip": "192.0.2.10",
                "state": "live",
                "status": "online",
                "ram": "25%",
                "disk": "20%",
            }
        ],
        "probe_status": "ok",
        "probe_state": "live",
    }
    serve._bg_cache_ts["fleet_overview"] = now
    serve._bg_cache_ts["health"] = now
    serve._bg_cache_errors.clear()


def _cleanup_hermetic_terminal_children() -> None:
    """Close live sessions and reap local PTY children at fixture shutdown."""
    with terminal._sessions_lock:
        for session_id in list(terminal._sessions):
            terminal._kill_session(session_id)

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid > 0:
            continue
        time.sleep(0.01)


class _HermeticInitProcess:
    """External child contract for the real web-init job state machine."""

    def __init__(self, cfg: FreqConfig, *, write_marker: bool = True):
        self.pid = os.getpid() + 1
        self.returncode = None
        self.stdout = self._output(cfg, write_marker)

    @staticmethod
    def _output(cfg: FreqConfig, write_marker: bool):
        yield "\x1b[1;36mPhase 6 / 12 - Fleet deployment\x1b[0m\n"
        time.sleep(1.2)
        if write_marker:
            marker = Path(cfg.conf_dir, ".initialized")
            marker.write_text("hermetic external init completed\n", encoding="utf-8")
        yield "\x1b[1;32mPhase 12 / 12 - Verification\x1b[0m\n"

    def wait(self):
        self.returncode = 0
        return self.returncode


def _generate_tls_certificate(root: Path) -> tuple[Path, Path]:
    tls_dir = root / "tls"
    tls_dir.mkdir(mode=0o700)
    cert = tls_dir / "localhost.crt"
    key = tls_dir / "localhost.key"
    result = subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("could not create the zero-state TLS certificate")
    key.chmod(0o600)
    cert.chmod(0o644)
    return cert, key


def _zero_state_file(path: str, label: str, expected: str | None = None) -> Path:
    candidate = Path(path)
    if not candidate.is_file():
        raise AssertionError(f"{label} adapter is missing")
    if stat.S_IMODE(candidate.stat().st_mode) != 0o600:
        raise AssertionError(f"{label} adapter mode is not 0600")
    if expected is not None and candidate.read_text(encoding="utf-8") != expected:
        raise AssertionError(f"{label} adapter content is incorrect")
    return candidate


def _validate_zero_state_init(
    cfg: FreqConfig,
    command,
    kwargs: dict,
    discovery_adapters: dict[str, str],
    *,
    empty_contract: bool = False,
) -> Path:
    """Consume the exact server-built init command and secret adapters."""
    if not isinstance(command, (list, tuple)):
        raise AssertionError("web init command must be an argv sequence")
    argv = [str(part) for part in command]
    env = kwargs.get("env")
    if kwargs.get("cwd") != cfg.install_dir:
        raise AssertionError("web init cwd does not match FREQ_DIR")
    if not isinstance(env, dict) or {
        key: env.get(key) for key in ("FREQ_DIR", "FREQ_WEB_INIT", "PYTHONUNBUFFERED")
    } != {"FREQ_DIR": cfg.install_dir, "FREQ_WEB_INIT": "1", "PYTHONUNBUFFERED": "1"}:
        raise AssertionError("web init environment is incorrect")
    expected_io = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
    }
    if any(kwargs.get(key) != value for key, value in expected_io.items()):
        raise AssertionError("web init process I/O contract is incorrect")
    for label in ("password", "known_hosts"):
        path = discovery_adapters.get(label)
        if not path or Path(path).exists():
            raise AssertionError(f"discovery {label} adapter was not removed before init")

    sudo_prefix = []
    if os.geteuid() != 0:
        sudo_prefix = [
            "sudo", "-n", "env", f"FREQ_DIR={cfg.install_dir}",
            "FREQ_WEB_INIT=1", "PYTHONUNBUFFERED=1",
        ]
    if argv[:len(sudo_prefix)] != sudo_prefix:
        raise AssertionError("web init privilege/environment prefix is incorrect")
    core = argv[len(sudo_prefix):]

    def flag_value(flag: str) -> str:
        if core.count(flag) != 1:
            raise AssertionError(f"web init requires exactly one {flag}")
        index = core.index(flag)
        if index + 1 >= len(core):
            raise AssertionError(f"web init {flag} has no value")
        return core[index + 1]

    service_file = flag_value("--password-file")
    service_account = flag_value("--service-account")
    if service_account not in {"freq-admin", "site-bootstrap"}:
        raise AssertionError("web init service account is outside the F3 identity challenge")
    bootstrap_file = flag_value("--bootstrap-password-file")
    contract_file = flag_value("--vm-contract")
    device_file = ""
    if empty_contract:
        if "--device-credentials" in core:
            raise AssertionError("empty contract emitted a device credential adapter")
    else:
        device_file = flag_value("--device-credentials")
    if any(argument in ZERO_STATE_SECRETS for argument in argv):
        raise AssertionError("submitted cleartext leaked into web init argv")
    code = "import sys; from freq.cli import main; raise SystemExit(main(sys.argv[1:]))"
    expected = [
        sys.executable, "-c", code, "--yes", "init", "--headless",
        "--password-file", service_file,
        "--bootstrap-user", "site-bootstrap",
        "--bootstrap-password-file", bootstrap_file,
        "--service-account", service_account,
        "--pve-nodes", "192.0.2.26",
        "--pve-node-names", "pve01",
        "--cluster-name", "dc01",
        "--ssh-mode", "sudo",
        "--vm-contract", contract_file,
    ]
    if device_file:
        expected.extend(["--device-credentials", device_file])
    expected.append("--skip-pdm")
    if core != expected:
        raise AssertionError("web init semantic argv is incorrect")

    service = _zero_state_file(service_file, "service password", "service-password\n")
    bootstrap = _zero_state_file(bootstrap_file, "bootstrap password", "bootstrap-password\n")
    contract = _zero_state_file(contract_file, "VM contract")
    device = _zero_state_file(device_file, "device credential") if device_file else None
    secret_dir = service.parent
    if stat.S_IMODE(secret_dir.stat().st_mode) != 0o700:
        raise AssertionError("web init secret directory mode is not 0700")
    if (
        bootstrap.parent != secret_dir
        or contract.parent != secret_dir
        or (device is not None and device.parent != secret_dir)
        or service.name != "service-account-password"
        or bootstrap.name != "bootstrap-password"
        or contract.name != "vm-contract.toml"
        or (device is not None and device.name != "device-credentials.toml")
    ):
        raise AssertionError("web init adapter paths are incorrect")

    with contract.open("rb") as handle:
        contract_data = tomllib.load(handle)
    expected_contract = {"fleet": {
        "owned_vmids": [] if empty_contract else [100],
        "template_vmids": [],
        "acknowledged_out_of_contract_vmids": [],
        "acknowledged_device_hosts": [] if empty_contract else ["192.0.2.99"],
    }}
    if contract_data != expected_contract:
        raise AssertionError("VM contract adapter truth is incorrect")
    if empty_contract:
        expected_names = {service.name, bootstrap.name, contract.name}
        if {path.name for path in secret_dir.iterdir()} != expected_names:
            raise AssertionError("empty web init secret directory contains unexpected adapters")
        return secret_dir

    with device.open("rb") as handle:
        device_data = tomllib.load(handle)
    if len(device_data) != 1:
        raise AssertionError("device credential adapter must contain one device")
    section, values = next(iter(device_data.items()))
    if not section.startswith("truenas-") or values != {
        "type": "truenas",
        "host": "192.0.2.10",
        "label": "truenas-192-0-2-10",
        "scope": "core",
        "user": "root",
        "password_file": str(secret_dir / f"{section}-password"),
    }:
        raise AssertionError("TrueNAS credential adapter truth is incorrect")
    nested = _zero_state_file(
        values["password_file"], "nested device password", "device-password\n"
    )
    expected_names = {
        service.name, bootstrap.name, contract.name, device.name, nested.name,
    }
    if {path.name for path in secret_dir.iterdir()} != expected_names:
        raise AssertionError("web init secret directory contains unexpected adapters")
    return secret_dir


def _install_zero_state_fixture(
    cfg: FreqConfig,
    *,
    resume_plan: bool = False,
    empty_contract: bool = False,
) -> list[str]:
    """Keep product setup logic real and replace external transports only."""
    serve.load_config = lambda *args, **kwargs: cfg
    auth.load_config = lambda *args, **kwargs: cfg
    if empty_contract:
        original_cleanup_expired_setup = auth._cleanup_expired_setup
        setattr(cfg, "_hermetic_setup_cleanup_recovered", False)

        def observe_expired_setup_cleanup(target_cfg):
            if (
                not Path(setup_state_path(target_cfg)).exists()
                and Path(contract_path(target_cfg)).exists()
            ):
                setattr(cfg, "_hermetic_setup_cleanup_recovered", True)
            return original_cleanup_expired_setup(target_cfg)

        auth._cleanup_expired_setup = observe_expired_setup_cleanup
        serve._cleanup_expired_setup = observe_expired_setup_cleanup

    discovery_adapters = {"password": "", "known_hosts": ""}
    init_attempts: list[str] = []
    first_attempt_state: dict[str, str] = {}
    previous_secret_dir: Path | None = None

    def cluster_resources(host, username, password_file):
        if host != "192.0.2.26" or username != "site-bootstrap":
            raise AssertionError("declared PVE bootstrap target or identity is incorrect")
        password = _zero_state_file(password_file, "discovery password", "bootstrap-password")
        known_hosts = Path(f"{password_file}.known-hosts")
        known_hosts.write_text("pve01 ssh-ed25519 HERMETIC-KEY\n", encoding="utf-8")
        known_hosts.chmod(0o600)
        discovery_adapters.update({"password": str(password), "known_hosts": str(known_hosts)})
        resources = [] if empty_contract else [
                {
                    "vmid": 100,
                    "type": "qemu",
                    "node": "pve01",
                    "name": "pve-freq",
                    "status": "running",
                    "ips": ["192.0.2.50"],
                }
            ]
        return resources, ""

    setup_discovery._ssh_cluster_resources = cluster_resources
    setup_discovery._ping = lambda ip: not empty_contract and ip in {"192.0.2.10", "192.0.2.99"}
    setup_discovery._http_fingerprint = lambda ip: (
        ("truenas", "https") if ip == "192.0.2.10" else ("unknown", "")
    )

    class ExternalProcesses:
        DEVNULL = subprocess.DEVNULL
        PIPE = subprocess.PIPE
        STDOUT = subprocess.STDOUT
        SubprocessError = subprocess.SubprocessError

        @staticmethod
        def Popen(command, *args, **kwargs):
            nonlocal previous_secret_dir
            if args:
                raise AssertionError("web init Popen received positional options")
            try:
                secret_dir = _validate_zero_state_init(
                    cfg,
                    command,
                    kwargs,
                    discovery_adapters,
                    empty_contract=empty_contract,
                )
                attempt = len(init_attempts) + 1
                if resume_plan:
                    state = load_setup_state(cfg)
                    contract = load_setup_contract(cfg)
                    identity = {
                        "setup_id": str(state.get("setup_id") or ""),
                        "discovery_id": str(state.get("active_discovery_id") or ""),
                        "contract_id": str(state.get("active_contract_id") or ""),
                        "job_id": str(state.get("active_init_job_id") or ""),
                    }
                    if state.get("phase") != "initializing" or not all(identity.values()):
                        raise AssertionError("init attempt did not own an initializing setup identity")
                    if not contract or contract.get("contract_id") != identity["contract_id"]:
                        raise AssertionError("init attempt did not retain the setup contract")
                    if attempt == 1:
                        first_attempt_state.update(identity)
                if resume_plan and attempt == 2:
                    if previous_secret_dir is None or previous_secret_dir.exists():
                        raise AssertionError("first init adapters remain before retry")
                    if any(identity[key] != first_attempt_state.get(key) for key in ("setup_id", "discovery_id", "contract_id")):
                        raise AssertionError("retry did not retain the original setup identity")
                    if identity["job_id"] == first_attempt_state.get("job_id"):
                        raise AssertionError("retry reused the failed init job")
                    if any(Path(cfg.conf_dir, marker).exists() for marker in (".initialized", ".web-setup-complete")):
                        raise AssertionError("failed init wrote a durable completion marker")
                    host = f"setup:{state.get('setup_id', '')}"
                    retained = {key for entry_host, key, _value in vault_list(cfg) if entry_host == host}
                    expected = {
                        "bootstrap_password",
                        credential_vault_key("device:truenas:192.0.2.10", "username"),
                        credential_vault_key("device:truenas:192.0.2.10", "password"),
                    }
                    if retained != expected:
                        raise AssertionError("failed init did not retain setup credential presence")
                if resume_plan and attempt > 2:
                    raise AssertionError("zero-state resume plan received an unexpected init attempt")
            except AssertionError as exc:
                print(f"HERMETIC_ZERO_STATE_CONTRACT_FAIL: {exc}", flush=True)
                raise
            write_marker = not resume_plan or attempt == 2
            init_attempts.append("success" if write_marker else "missing-marker")
            previous_secret_dir = secret_dir
            return _HermeticInitProcess(cfg, write_marker=write_marker)

        @staticmethod
        def run(command, *args, **kwargs):
            if args or command != ["systemctl", "cat", "freq-serve.service"]:
                raise AssertionError("unexpected zero-state external command")
            expected = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "timeout": 5}
            if kwargs != expected:
                raise AssertionError("service-absent probe options are incorrect")
            return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"")

    serve.subprocess = ExternalProcesses
    return init_attempts


def _audit_zero_state_disk(cfg: FreqConfig, init_attempts: list[str] | None = None) -> list[str]:
    """Return named disk-truth failures without echoing submitted secrets."""
    failures = []
    if getattr(cfg, "_hermetic_setup_cleanup_recovered", False):
        failures.append("setup contract required observation-time recovery")
    users_file = Path(cfg.conf_dir, "users.conf")
    if not users_file.is_file():
        failures.append("users.conf missing")
        users_text = ""
    else:
        users_text = users_file.read_text(encoding="utf-8")
        if "admin admin" not in users_text:
            failures.append("first operator missing from users.conf")
        if any(secret in users_text for secret in ZERO_STATE_SECRETS):
            failures.append("users.conf contains submitted cleartext")

    vault_file = Path(cfg.vault_file)
    if not vault_file.is_file():
        failures.append("encrypted vault missing")
        vault_bytes = b""
    else:
        vault_bytes = vault_file.read_bytes()
        if not vault_bytes.startswith(b"Salted__"):
            failures.append("vault is not OpenSSL encrypted")
        if any(secret.encode() in vault_bytes for secret in ZERO_STATE_SECRETS):
            failures.append("vault contains submitted cleartext")
    entries = vault_list(cfg) if vault_file.is_file() else []
    if not any(host == "auth" and key == "password_admin" for host, key, _ in entries):
        failures.append("operator password hash missing from vault")
    if any(host.startswith("setup:") for host, _key, _value in entries):
        failures.append("setup vault namespace remains")

    if Path(setup_state_path(cfg)).exists():
        failures.append("setup state remains")
    if Path(contract_path(cfg)).exists():
        failures.append("setup contract remains")
    for marker in (Path(cfg.conf_dir, ".initialized"), Path(cfg.conf_dir, ".web-setup-complete")):
        if not marker.is_file():
            failures.append(f"completion marker missing: {marker.name}")

    job = (serve._setup_init_snapshot() or {}).get("job") or {}
    job_id = str(job.get("id") or "")
    if not job_id:
        failures.append("completed init job missing")
    elif Path(cfg.data_dir, "secrets", "setup-init", job_id).exists():
        failures.append("transient init adapter directory remains")
    if init_attempts is not None and init_attempts != ["missing-marker", "success"]:
        failures.append("zero-state resume attempt plan did not finish exactly")
    return failures


def _audit_first_admin_claim_disk(cfg: FreqConfig) -> list[str]:
    """Audit the bounded first-admin-only browser/direct-client fixture."""
    from freq.core import first_admin_claim

    failures = []
    users_file = Path(cfg.conf_dir, "users.conf")
    users_text = users_file.read_text(encoding="utf-8") if users_file.is_file() else ""
    if users_text.count("admin admin") != 1:
        failures.append("first-admin fixture did not persist exactly one admin")
    state_path = Path(first_admin_claim.claim_state_path(cfg))
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        failures.append("first-admin claim state is unreadable after commit")
        state = {}
    if state.get("state") != "consumed" or "digest" in state:
        failures.append("first-admin claim did not close digest-free")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument(
        "--tls",
        action="store_true",
        help="serve the configured hermetic profile over throwaway self-signed TLS",
    )
    parser.add_argument(
        "--profile",
        choices=(
            "configured",
            "first-admin-claim",
            "zero-state",
            "zero-state-resume",
            "zero-state-empty",
        ),
        default="configured",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="pve-freq-dashboard-") as tmp:
        root = Path(tmp)
        cfg = _config(root)
        zero_state = args.profile in {
            "first-admin-claim",
            "zero-state",
            "zero-state-resume",
            "zero-state-empty",
        }
        init_attempts = None
        claim_metadata = None
        claim_delivery_path = None
        tls_enabled = zero_state or args.tls
        if tls_enabled:
            cert, key = _generate_tls_certificate(root)
            cfg.tls_cert = str(cert)
            cfg.tls_key = str(key)
        if zero_state:
            init_attempts = _install_zero_state_fixture(
                cfg,
                resume_plan=args.profile == "zero-state-resume",
                empty_contract=args.profile == "zero-state-empty",
            )
            claim_metadata, claim_delivery_path = _prepare_hermetic_first_admin_claim(cfg, root)
        else:
            _install_fixture(cfg)
        httpd = serve.ThreadedHTTPServer(("127.0.0.1", args.port), serve.FreqHandler)
        if tls_enabled:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cfg.tls_cert, cfg.tls_key)
            httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

        def stop(signum, frame):
            del signum, frame
            threading.Thread(target=httpd.shutdown, daemon=True).start()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        label = "HERMETIC_ZERO_STATE" if zero_state else "HERMETIC_DASHBOARD"
        protocol = "https" if tls_enabled else "http"
        if zero_state:
            print(
                "HERMETIC_FIRST_ADMIN_CLAIM_FILE "
                f"{claim_delivery_path} CLAIM_ID {claim_metadata['claim_id']}",
                flush=True,
            )
        print(f"{label} {protocol}://127.0.0.1:{httpd.server_port}", flush=True)
        try:
            httpd.serve_forever()
        finally:
            httpd.server_close()
            if not zero_state:
                _cleanup_hermetic_terminal_children()
        if zero_state:
            if args.profile == "first-admin-claim":
                failures = _audit_first_admin_claim_disk(cfg)
            else:
                failures = _audit_zero_state_disk(
                    cfg,
                    init_attempts if args.profile == "zero-state-resume" else None,
                )
            if claim_delivery_path.exists():
                failures.append("first-admin claim delivery adapter was not consumed")
            if failures:
                label = (
                    "HERMETIC_FIRST_ADMIN_CLAIM_AUDIT"
                    if args.profile == "first-admin-claim"
                    else "HERMETIC_ZERO_STATE_AUDIT"
                )
                print(label + " FAIL: " + "; ".join(failures), flush=True)
                return 1
            print(
                "HERMETIC_FIRST_ADMIN_CLAIM_AUDIT PASS"
                if args.profile == "first-admin-claim"
                else "HERMETIC_ZERO_STATE_AUDIT PASS",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
