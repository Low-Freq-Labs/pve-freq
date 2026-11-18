"""Least-privilege setup secret inputs and credential materialization."""

import os
import re
import subprocess
import sys
import uuid

from freq.core.config import is_managed_service_account_name
from freq.core.device_credentials import device_credentials_section_header
from freq.core.setup_contract import SetupContractError
from freq.core.setup_paths import legacy_init_input_candidate
from freq.core.setup_state import SCHEMA as ZERO_STATE_WEB_SCHEMA
from freq.core.vault_key_input import _VaultKeyReadDuty
from freq.core.vault_decrypt_input import _VaultDecryptReadDuty
from freq.core.vault_pipe_input import _VaultPipeReadDuty
from freq.core.vault_child_input import _VaultChildReadDuty
from freq.core.vault_child_context import _VaultChildContextDuty
from freq.core.vault_child_constructor import _VaultChildConstructorDuty


def resolved_bootstrap_username(discovery):
    """Return the effective bootstrap identity retained by discovery."""
    value = (discovery or {}).get("bootstrap_username")
    return str(value or "root").strip().lower() or "root"


def validate_init_request(body, state, contract, discovery):
    """Validate the value-only zero-state init request."""
    if not isinstance(body, dict):
        raise SetupContractError("invalid_json", "JSON object required.")
    allowed = {
        "schema", "setup_id", "discovery_id", "contract_id",
        "client_request_id", "service_account", "options",
    }
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise SetupContractError(
            "unsupported_field", f"Unsupported init field: {unknown[0]}", unknown[0]
        )
    if body.get("schema") != ZERO_STATE_WEB_SCHEMA:
        raise SetupContractError("unsupported_schema", "Unsupported setup schema.", "schema")
    identities = (
        ("setup_id", state.get("setup_id"), "setup_expired", 410),
        ("discovery_id", discovery.get("id"), "stale_discovery", 409),
        ("contract_id", contract.get("contract_id"), "stale_contract", 409),
    )
    for field, expected, code, status in identities:
        if not expected or str(body.get(field) or "") != str(expected):
            raise SetupContractError(code, f"The {field.replace('_', ' ')} is stale.", field, status)
    request_id = str(body.get("client_request_id") or "").strip()
    try:
        uuid.UUID(request_id)
    except ValueError as exc:
        raise SetupContractError(
            "invalid_client_request_id", "client_request_id must be a UUID.", "client_request_id"
        ) from exc

    service = body.get("service_account")
    if not isinstance(service, dict):
        raise SetupContractError("required_field", "service_account is required.", "service_account")
    unknown_service = sorted(set(service) - {"username", "password"})
    if unknown_service:
        field = f"service_account.{unknown_service[0]}"
        raise SetupContractError("unsupported_field", "Unsupported service account field.", field)
    username = str(service.get("username") or "").strip()
    password = service.get("password")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username):
        raise SetupContractError(
            "invalid_service_account", "Service account username is invalid.", "service_account.username", 422
        )
    bootstrap_username = resolved_bootstrap_username(discovery)
    if username.lower() == bootstrap_username:
        raise SetupContractError(
            "service_account_matches_bootstrap",
            "Service account must differ from the bootstrap SSH login.",
            "service_account.username",
            422,
        )
    if not is_managed_service_account_name(username, bootstrap_user=bootstrap_username):
        raise SetupContractError(
            "invalid_service_account",
            "Service account username must be a valid non-root account.",
            "service_account.username",
            422,
        )
    if (
        not isinstance(password, str)
        or len(password) < 8
        or len(password.encode("utf-8")) > 4096
        or "\x00" in password
        or "\n" in password
        or "\r" in password
    ):
        raise SetupContractError(
            "invalid_service_password", "Service account password is invalid.", "service_account.password", 422
        )
    if len(password) > 20 and any(
        str(device.get("kind") or "").lower() == "idrac"
        for device in contract.get("owned_devices") or []
    ):
        raise SetupContractError(
            "service_password_device_limit",
            "Service account password must be at most 20 characters when iDRAC is owned.",
            "service_account.password",
            422,
        )

    options = body.get("options") or {}
    if not isinstance(options, dict):
        raise SetupContractError("invalid_options", "options must be an object.", "options")
    unknown_options = sorted(set(options) - {"ssh_mode", "pdm", "ssl"})
    if unknown_options:
        raise SetupContractError(
            "unsupported_field", "Unsupported init option.", f"options.{unknown_options[0]}"
        )
    ssh_mode = str(options.get("ssh_mode") or "sudo").strip().lower()
    if ssh_mode != "sudo":
        raise SetupContractError("invalid_ssh_mode", "ssh_mode must be sudo.", "options.ssh_mode", 422)
    pdm = options.get("pdm") or {"mode": "skip"}
    ssl_options = options.get("ssl") or {"mode": "defer"}
    if not isinstance(pdm, dict) or sorted(set(pdm) - {"mode", "password"}):
        raise SetupContractError("invalid_pdm_options", "Invalid PDM options.", "options.pdm", 422)
    if not isinstance(ssl_options, dict) or set(ssl_options) != {"mode"}:
        raise SetupContractError("invalid_ssl_options", "Invalid SSL options.", "options.ssl", 422)
    pdm_mode = str(pdm.get("mode") or "skip").strip().lower()
    if pdm_mode not in {"skip", "install"}:
        raise SetupContractError("invalid_pdm_mode", "PDM mode is invalid.", "options.pdm.mode", 422)
    if str(ssl_options.get("mode") or "defer").strip().lower() != "defer":
        raise SetupContractError("invalid_ssl_mode", "SSL mode must be defer.", "options.ssl.mode", 422)
    pdm_password = pdm.get("password", "")
    if pdm_mode == "install" and (
        not isinstance(pdm_password, str)
        or not pdm_password
        or len(pdm_password.encode("utf-8")) > 4096
        or "\x00" in pdm_password
        or "\n" in pdm_password
        or "\r" in pdm_password
    ):
        raise SetupContractError(
            "required_field", "PDM password is required for install mode.", "options.pdm.password", 422
        )
    if pdm_mode == "skip" and "password" in pdm:
        raise SetupContractError(
            "unsupported_field",
            "PDM password is not accepted in skip mode.",
            "options.pdm.password",
            422,
        )
    return {
        "client_request_id": request_id,
        "service_account": {"username": username, "password": password},
        "ssh_mode": ssh_mode,
        "pdm_mode": pdm_mode,
        "pdm_password": pdm_password,
    }


_SETUP_VM_CONTRACT_DUTY_OMITTED = object()


def write_vm_contract(secret_dir, contract, *, _duty=_SETUP_VM_CONTRACT_DUTY_OMITTED):
    if _duty is _SETUP_VM_CONTRACT_DUTY_OMITTED:
        path = os.path.join(secret_dir, "vm-contract.toml")
        lines = [
            "[fleet]",
            f"owned_vmids = {toml_scalar(contract.get('owned_vmids') or [])}",
            f"template_vmids = {toml_scalar(contract.get('template_vmids') or [])}",
            "acknowledged_out_of_contract_vmids = "
            + toml_scalar(contract.get("acknowledged_out_of_contract_vmids") or []),
            "acknowledged_device_hosts = "
            + toml_scalar(
                sorted(
                    {
                        str(device.get("host") or "").strip()
                        for device in contract.get("acknowledged_devices") or []
                        if str(device.get("host") or "").strip()
                    }
                )
            ),
            "",
        ]
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        os.chmod(path, 0o600)
        return path
    if type(_duty) is not _SetupInitVMContractDuty:
        raise SetupContractError('init_prepare_failed',
            'Setup contract acquisition is unavailable.', status=500)
    try:
        _duty.enter(secret_dir, contract)
        path = os.path.join(secret_dir, "vm-contract.toml")
        _duty.candidate_path = path
        lines = [
            "[fleet]",
            f"owned_vmids = {toml_scalar(contract.get('owned_vmids') or [])}",
            f"template_vmids = {toml_scalar(contract.get('template_vmids') or [])}",
            "acknowledged_out_of_contract_vmids = "
            + toml_scalar(contract.get("acknowledged_out_of_contract_vmids") or []),
            "acknowledged_device_hosts = "
            + toml_scalar(
                sorted(
                    {
                        str(device.get("host") or "").strip()
                        for device in contract.get("acknowledged_devices") or []
                        if str(device.get("host") or "").strip()
                    }
                )
            ),
            "",
        ]
        _duty.format_stage = 'returned'
        _duty.open_stage = 'pending'
        handle = open(path, "w", encoding="utf-8")
        _duty.handle = handle
        _duty.open_stage = 'returned'
    except BaseException as failure:
        _duty.remember(0, failure)
        raise _duty.failure from None
    _duty.enter_stage = 'pending'
    try:
        with handle as output:
            _duty.enter_stage = 'returned'
            _duty.entered_handle = output
            try:
                if output is not handle:
                    raise SetupContractError('init_prepare_failed',
                        'Setup contract acquisition is unavailable.', status=500)
                _duty.body_stage = 'pending'
                output.write("\n".join(lines))
            except BaseException as failure:
                _duty.remember(2, failure)
            else:
                _duty.body_stage = 'returned'
            finally:
                _duty.exit_stage = 'pending'
    except BaseException as failure:
        _duty.remember(1 if _duty.enter_stage != 'returned' else 3, failure)
    else:
        _duty.exit_stage = 'returned'
    if _duty.failure is not None:
        raise _duty.failure from None
    _duty.mode_stage = 'pending'
    try:
        os.chmod(path, 0o600)
    except BaseException as failure:
        _duty.remember(4, failure)
        raise _duty.failure from None
    _duty.mode_stage = 'returned'
    _duty.result_path = path
    _duty.result_stage = 'stored'
    return path


def list_value(value):
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in re.split(r"[,\s]+", str(value or "")) if v.strip()]


def toml_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_scalar(v) for v in value) + "]"
    escaped = (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\b", "\\b")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\f", "\\f")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


_SETUP_SECRET_FILE_DUTY_OMITTED = object()


class _SetupInitSecretFileDuty:
    """One fixed original secret writer's retained handle and raw outcomes."""
    __slots__ = ('directory', 'launch', 'job', 'cfg', 'name', 'used',
                 'candidate_path', 'handle', 'entered_handle', 'result_path',
                 'open_stage', 'enter_stage', 'body_stage', 'exit_stage',
                 'mode_stage', 'result_stage', 'caller_returned', 'pdm_mode',
                 'failures', 'first_failures', 'latest_failure', 'failure')

    def __init__(self, directory, *, _name='service-account-password'):
        self.directory = directory
        self.launch, self.job, self.cfg = directory.launch, directory.job, directory.cfg
        self.name = _name
        self.pdm_mode = None
        self.used = self.caller_returned = False
        self.candidate_path = self.handle = self.entered_handle = self.result_path = None
        self.open_stage = self.enter_stage = self.body_stage = self.exit_stage = 'unused'
        self.mode_stage = self.result_stage = 'unused'
        self.failures = [None] * 5
        self.first_failures = [None] * 3
        self.latest_failure = self.failure = None

    def remember(self, index, failure):
        self.latest_failure = failure
        if self.failures[index] is None:
            self.failures[index] = failure
        if not issubclass(type(failure), Exception):
            kind = 0
        elif issubclass(type(failure), MemoryError):
            kind = 1
        else:
            kind = 2
        if self.first_failures[kind] is None:
            self.first_failures[kind] = failure
        for first in self.first_failures:
            if first is not None:
                self.failure = first
                break

    def enter(self, secret_dir, name):
        if self.used:
            first = self.failure
            if first is not None and (not issubclass(type(first), Exception)
                                      or issubclass(type(first), MemoryError)):
                raise first from None
            raise SetupContractError('init_prepare_failed',
                'Setup secret acquisition is unavailable.', status=500)
        self.used = True
        directory = self.directory
        if (type(directory) is not _SetupInitDirectoryDuty
                or not (self.name == 'service-account-password' and directory.service_file is self
                        or self.name == 'bootstrap-password' and directory.bootstrap_file is self
                        or self.name == 'pdm-password' and directory.pdm_file is self)
                or directory.launch is not self.launch or directory.job is not self.job
                or directory.cfg is not self.cfg
                or self.job.get('_worker_launch') is not self.launch
                or self.launch.preparation.directory is not directory
                or directory.caller_returned is not True
                or directory.failure is not None
                or directory.result_path is not secret_dir
                or name != self.name):
            raise SetupContractError('init_prepare_failed',
                'Setup secret acquisition is unavailable.', status=500)
        if self.name == 'bootstrap-password':
            lookup = directory.bootstrap_lookup
            if (type(lookup) is not _SetupBootstrapLookupDuty
                    or lookup.directory is not directory or lookup.launch is not self.launch
                    or lookup.job is not self.job or lookup.cfg is not self.cfg
                    or lookup.setup_id != self.job.get('setup_id')
                    or lookup.setup_id != self.launch.preparation.contract.get('setup_id')
                    or lookup.cred_key != 'bootstrap_password'
                    or lookup.used is not True or lookup.stage != 'returned'
                    or lookup.passed_empty_check is not True or lookup.failure is not None):
                raise SetupContractError('init_prepare_failed',
                    'Setup bootstrap file acquisition is unavailable.', status=500)
        if self.name == 'pdm-password':
            device = directory.device_credentials
            if (type(device) is not _SetupDeviceMaterializationDuty
                    or device.directory is not directory or device.launch is not self.launch
                    or device.job is not self.job or device.cfg is not self.cfg
                    or device.contract is not self.launch.preparation.contract
                    or device.stage != 'returned' or device.caller_returned is not True
                    or device.entry_stage != 'returned' or device.gate_stage != 'returned'
                    or device.body_stage != 'returned' or device.result_stage != 'stored'
                    or device.failure is not None):
                raise SetupContractError('init_prepare_failed',
                    'Setup PDM acquisition is unavailable.', status=500)
            mode = self.launch.preparation.request.get('pdm_mode')
            if mode not in ('install', 'skip'):
                raise SetupContractError('init_prepare_failed',
                    'Setup PDM acquisition is unavailable.', status=500)
            self.pdm_mode = mode


class _SetupInitVMContractDuty(_SetupInitSecretFileDuty):
    """Original contract formatter/file observations; no native ownership grant."""
    __slots__ = ('contract', 'format_stage')

    def __init__(self, directory):
        super().__init__(directory, _name='vm-contract.toml')
        self.contract = None
        self.format_stage = 'unused'

    def enter(self, secret_dir, contract):
        if self.used:
            first = self.failure
            if first is not None and (not issubclass(type(first), Exception)
                                      or issubclass(type(first), MemoryError)):
                raise first from None
            raise SetupContractError('init_prepare_failed',
                'Setup contract acquisition is unavailable.', status=500)
        self.used = True
        self.format_stage = 'pending'
        directory = self.directory
        if (type(directory) is not _SetupInitDirectoryDuty
                or directory.vm_contract is not self
                or directory.launch is not self.launch or directory.job is not self.job
                or directory.cfg is not self.cfg or self.launch.job is not self.job
                or self.job.get('_worker_launch') is not self.launch
                or self.launch.preparation.directory is not directory
                or self.launch.preparation.contract is not contract
                or self.launch.preparation.cfg is not self.cfg
                or directory.caller_returned is not True or directory.failure is not None
                or directory.result_path is not secret_dir
                or self.name != 'vm-contract.toml'):
            raise SetupContractError('init_prepare_failed',
                'Setup contract acquisition is unavailable.', status=500)
        bootstrap = directory.bootstrap_file
        if (type(bootstrap) is not _SetupInitSecretFileDuty
                or bootstrap.directory is not directory or bootstrap.launch is not self.launch
                or bootstrap.job is not self.job or bootstrap.cfg is not self.cfg
                or bootstrap.name != 'bootstrap-password'
                or bootstrap.caller_returned is not True or bootstrap.failure is not None
                or bootstrap.result_stage != 'stored'
                or bootstrap.result_path is not bootstrap.candidate_path):
            raise SetupContractError('init_prepare_failed',
                'Setup contract acquisition is unavailable.', status=500)
        lookup = directory.bootstrap_lookup
        if (type(lookup) is not _SetupBootstrapLookupDuty
                or lookup.directory is not directory or lookup.launch is not self.launch
                or lookup.job is not self.job or lookup.cfg is not self.cfg
                or lookup.setup_id != self.job.get('setup_id')
                or lookup.setup_id != contract.get('setup_id')
                or lookup.used is not True or lookup.stage != 'returned'
                or lookup.passed_empty_check is not True or lookup.failure is not None):
            raise SetupContractError('init_prepare_failed',
                'Setup contract acquisition is unavailable.', status=500)
        self.contract = contract


class _SetupBootstrapLookupDuty:
    """One original lookup observation; never stores the credential value."""
    __slots__ = ('directory', 'launch', 'job', 'cfg', 'setup_id', 'cred_key',
                 'used', 'stage', 'requested_host', 'passed_empty_check',
                 'first_failures', 'latest_failure', 'failure', 'key_read', 'decrypt_read')

    def __init__(self, directory):
        self.directory = directory
        self.launch, self.job, self.cfg = directory.launch, directory.job, directory.cfg
        self.setup_id = self.job.get('setup_id')
        self.cred_key = 'bootstrap_password'
        self.used = self.passed_empty_check = False
        self.stage = 'unused'
        self.requested_host = None
        self.first_failures = [None] * 3
        self.latest_failure = self.failure = None
        self.key_read = _VaultKeyReadDuty(self)
        self.decrypt_read = _VaultDecryptReadDuty(self)
        self.decrypt_read.pipe_read = _VaultPipeReadDuty(self.decrypt_read)
        self.decrypt_read.pipe_read.child_read = _VaultChildReadDuty(self.decrypt_read.pipe_read)
        self.decrypt_read.pipe_read.child_read.context_read = _VaultChildContextDuty(self.decrypt_read.pipe_read.child_read)
        self.decrypt_read.pipe_read.child_read.constructor_read = _VaultChildConstructorDuty(self.decrypt_read.pipe_read.child_read)

    def remember(self, failure):
        self.latest_failure = failure
        if not issubclass(type(failure), Exception):
            kind = 0
        elif issubclass(type(failure), MemoryError):
            kind = 1
        else:
            kind = 2
        if self.first_failures[kind] is None:
            self.first_failures[kind] = failure
        for first in self.first_failures:
            if first is not None:
                self.failure = first
                break

    def enter(self, cfg, contract):
        try:
            if self.used:
                first = self.failure
                if first is not None and (not issubclass(type(first), Exception)
                                          or issubclass(type(first), MemoryError)):
                    raise first from None
                raise SetupContractError('init_prepare_failed',
                    'Setup bootstrap acquisition is unavailable.', status=500)
            self.used = True
            self.stage = 'host_pending'
            directory = self.directory
            preparation = self.launch.preparation
            service_file = directory.service_file
            if (type(directory) is not _SetupInitDirectoryDuty
                    or directory.bootstrap_lookup is not self
                    or directory.launch is not self.launch or directory.job is not self.job
                    or directory.cfg is not self.cfg or self.cfg is not cfg
                    or self.launch.job is not self.job
                    or self.job.get('_worker_launch') is not self.launch
                    or preparation.directory is not directory or preparation.cfg is not cfg
                    or preparation.contract is not contract
                    or not self.setup_id or self.job.get('setup_id') != self.setup_id
                    or contract.get('setup_id') != self.setup_id
                    or self.cred_key != 'bootstrap_password'
                    or directory.caller_returned is not True or directory.failure is not None
                    or type(service_file) is not _SetupInitSecretFileDuty
                    or service_file.directory is not directory
                    or service_file.caller_returned is not True
                    or service_file.failure is not None):
                raise SetupContractError('init_prepare_failed',
                    'Setup bootstrap acquisition is unavailable.', status=500)
        except BaseException as failure:
            # Root duplicate/association failure even if a delegate catches it.
            self.remember(failure)
            raise self.failure from None


class _SetupDeviceMaterializationDuty:
    """Original whole-call/source-context observations, never secret storage."""
    __slots__ = ('directory', 'launch', 'job', 'cfg', 'setup_id', 'contract',
                 'used', 'stage', 'gate', 'entry_stage', 'gate_stage', 'body_stage',
                 'result_path', 'result_stage', 'caller_returned', 'failures',
                 'first_failures', 'latest_failure', 'failure')

    def __init__(self, directory):
        self.directory = directory
        self.launch, self.job, self.cfg = directory.launch, directory.job, directory.cfg
        self.setup_id = self.job.get('setup_id')
        self.contract = self.gate = self.result_path = None
        self.used = self.caller_returned = False
        self.stage = self.entry_stage = self.gate_stage = self.body_stage = 'unused'
        self.result_stage = 'unused'
        self.failures = [None] * 3
        self.first_failures = [None] * 3
        self.latest_failure = self.failure = None

    def remember(self, index, failure):
        self.latest_failure = failure
        if self.failures[index] is None:
            self.failures[index] = failure
        if not issubclass(type(failure), Exception):
            kind = 0
        elif issubclass(type(failure), MemoryError):
            kind = 1
        else:
            kind = 2
        if self.first_failures[kind] is None:
            self.first_failures[kind] = failure
        for first in self.first_failures:
            if first is not None:
                self.failure = first
                break

    def enter(self, cfg, secret_dir, contract):
        try:
            if self.used:
                first = self.failure
                if first is not None and (not issubclass(type(first), Exception)
                                          or issubclass(type(first), MemoryError)):
                    raise first from None
                raise SetupContractError('init_prepare_failed',
                    'Setup device materialization is unavailable.', status=500)
            self.used = True
            self.stage = 'pending'
            directory = self.directory
            if (type(directory) is not _SetupInitDirectoryDuty
                    or directory.device_credentials is not self
                    or directory.launch is not self.launch or directory.job is not self.job
                    or directory.cfg is not self.cfg or self.cfg is not cfg
                    or self.launch.job is not self.job
                    or self.job.get('_worker_launch') is not self.launch
                    or self.launch.preparation.directory is not directory
                    or self.launch.preparation.contract is not contract
                    or self.launch.preparation.cfg is not cfg
                    or not self.setup_id or self.job.get('setup_id') != self.setup_id
                    or contract.get('setup_id') != self.setup_id
                    or directory.result_path is not secret_dir
                    or directory.caller_returned is not True or directory.failure is not None):
                raise SetupContractError('init_prepare_failed',
                    'Setup device materialization is unavailable.', status=500)
            vm = directory.vm_contract
            if (type(vm) is not _SetupInitVMContractDuty
                    or vm.directory is not directory or vm.launch is not self.launch
                    or vm.job is not self.job or vm.cfg is not cfg or vm.contract is not contract
                    or vm.caller_returned is not True or vm.failure is not None
                    or vm.result_stage != 'stored' or vm.result_path is not vm.candidate_path):
                raise SetupContractError('init_prepare_failed',
                    'Setup device materialization is unavailable.', status=500)
            self.contract = contract
        except BaseException as failure:
            self.remember(0, failure)
            raise self.failure from None


class _SetupInitDirectoryDuty:
    """Negative journal for one original directory helper, never path authority."""
    __slots__ = ('launch', 'job', 'cfg', 'job_id', 'used', 'candidate_path',
                 'result_path', 'mkdir_stage', 'chmod_stage', 'result_stage',
                 'caller_returned', 'ignored_mode_error', 'failure',
                 'latest_failure', 'first_failures', 'service_file', 'bootstrap_lookup', 'bootstrap_file', 'vm_contract', 'device_credentials', 'pdm_file')

    def __init__(self, launch, cfg):
        self.launch, self.job, self.cfg = launch, launch.job, cfg
        self.job_id = self.job['id']
        self.used = self.caller_returned = False
        self.candidate_path = self.result_path = None
        self.mkdir_stage = self.chmod_stage = self.result_stage = 'unused'
        self.ignored_mode_error = self.failure = self.latest_failure = None
        self.first_failures = [None] * 3
        self.service_file = _SetupInitSecretFileDuty(self)
        self.bootstrap_lookup = _SetupBootstrapLookupDuty(self)
        self.bootstrap_file = _SetupInitSecretFileDuty(self, _name='bootstrap-password')
        self.vm_contract = _SetupInitVMContractDuty(self)
        self.device_credentials = _SetupDeviceMaterializationDuty(self)
        self.pdm_file = _SetupInitSecretFileDuty(self, _name='pdm-password')

    def remember(self, failure):
        self.latest_failure = failure
        if not issubclass(type(failure), Exception):
            index = 0
        elif issubclass(type(failure), MemoryError):
            index = 1
        else:
            index = 2
        if self.first_failures[index] is None:
            self.first_failures[index] = failure
        for first in self.first_failures:
            if first is not None:
                self.failure = first
                break

    def enter(self, cfg, job_id):
        if self.used:
            first = self.failure
            if first is not None and (not issubclass(type(first), Exception)
                                      or issubclass(type(first), MemoryError)):
                raise first from None
            raise SetupContractError('init_prepare_failed',
                'Setup adapter acquisition is unavailable.', status=500)
        self.used = True
        if (self.cfg is not cfg or self.job_id != job_id
                or self.launch.job is not self.job
                or self.job.get('_worker_launch') is not self.launch
                or self.launch.preparation.directory is not self):
            raise SetupContractError('init_prepare_failed',
                'Setup adapter acquisition is unavailable.', status=500)


def setup_secret_dir(cfg, job_id, *, _duty=None):
    if _duty is not None and type(_duty) is not _SetupInitDirectoryDuty:
        raise SetupContractError('init_prepare_failed',
            'Setup adapter acquisition is unavailable.', status=500)
    try:
        if _duty is not None:
            _duty.enter(cfg, job_id)
        path = os.path.join(cfg.data_dir, "secrets", "setup-init", job_id)
        if _duty is not None:
            _duty.candidate_path = path
            _duty.mkdir_stage = 'pending'
        os.makedirs(path, mode=0o700, exist_ok=True)
        if _duty is not None:
            _duty.mkdir_stage = 'returned'
            _duty.chmod_stage = 'pending'
        try:
            os.chmod(path, 0o700)
        except OSError as failure:
            if _duty is not None:
                _duty.ignored_mode_error = failure
                _duty.chmod_stage = 'ignored'
        else:
            if _duty is not None:
                _duty.chmod_stage = 'returned'
        if _duty is not None:
            # Storage precedes helper return; caller receipt is independent.
            _duty.result_path = path
            _duty.result_stage = 'stored'
        return path
    except BaseException as failure:
        if _duty is not None:
            _duty.remember(failure)
        raise


def write_setup_secret(secret_dir, name, value, *, _duty=_SETUP_SECRET_FILE_DUTY_OMITTED):
    if _duty is _SETUP_SECRET_FILE_DUTY_OMITTED:
        # Preserve the original omitted-keyword helper and all legacy callers.
        if not value:
            return ""
        path = os.path.join(secret_dir, name)
        with open(path, "w") as f:
            f.write(str(value))
            if not str(value).endswith("\n"):
                f.write("\n")
        os.chmod(path, 0o600)
        return path
    if type(_duty) is not _SetupInitSecretFileDuty:
        raise SetupContractError('init_prepare_failed',
            'Setup secret acquisition is unavailable.', status=500)
    try:
        _duty.enter(secret_dir, name)
        if not value:
            _duty.result_path = ""
            _duty.result_stage = 'empty'
            return ""
        path = os.path.join(secret_dir, name)
        _duty.candidate_path = path
        _duty.open_stage = 'pending'
        handle = open(path, "w")
        _duty.handle = handle
        _duty.open_stage = 'returned'
    except BaseException as failure:
        _duty.remember(0, failure)
        raise _duty.failure from None
    _duty.enter_stage = 'pending'
    try:
        with handle as f:
            _duty.enter_stage = 'returned'
            _duty.entered_handle = f
            try:
                if f is not handle:
                    raise SetupContractError('init_prepare_failed',
                        'Setup secret acquisition is unavailable.', status=500)
                _duty.body_stage = 'pending'
                f.write(str(value))
                if not str(value).endswith("\n"):
                    f.write("\n")
            except BaseException as failure:
                # Native text-file exit still closes independently. Retain the
                # body raw object before it can be replaced during that exit.
                _duty.remember(2, failure)
            else:
                _duty.body_stage = 'returned'
            finally:
                _duty.exit_stage = 'pending'
    except BaseException as failure:
        # Failed entry has not entered its exit; retain its returned handle
        # without inventing a new close or recovery attempt.
        _duty.remember(1 if _duty.enter_stage != 'returned' else 3, failure)
    else:
        _duty.exit_stage = 'returned'
    if _duty.failure is not None:
        raise _duty.failure from None
    _duty.mode_stage = 'pending'
    try:
        os.chmod(path, 0o600)
    except BaseException as failure:
        _duty.remember(4, failure)
        raise _duty.failure from None
    _duty.mode_stage = 'returned'
    _duty.result_path = path
    _duty.result_stage = 'stored'
    return path


def write_setup_device_credentials(secret_dir, device_credentials):
    if not isinstance(device_credentials, dict) or not device_credentials:
        return ""
    lines = []
    type_sections = {
        "pfsense": "pfsense",
        "truenas": "truenas",
        "switch": "switch",
        "bmc": "idrac",
        "idrac": "idrac",
    }
    for section, raw in device_credentials.items():
        if not isinstance(raw, dict):
            continue
        row_type = str(raw.get("type") or "").strip().lower()
        section_name = type_sections.get(row_type) or str(section).strip()
        safe_section = re.sub(r"[^A-Za-z0-9_.:-]", "", section_name)
        if not safe_section:
            continue
        lines.append(device_credentials_section_header(safe_section))
        normalized = dict(raw)
        if normalized.get("username") and not normalized.get("user"):
            normalized["user"] = normalized.get("username")
        if normalized.get("secret") and not normalized.get("password"):
            normalized["password"] = normalized.get("secret")
        if normalized.get("target"):
            target = str(normalized.get("target") or "").strip()
            if target:
                if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", target) and not normalized.get("host"):
                    normalized["host"] = target
                elif not normalized.get("label"):
                    normalized["label"] = target
        for key, value in normalized.items():
            if value in (None, ""):
                continue
            if key == "password":
                pw_path = write_setup_secret(secret_dir, f"{safe_section}-password", value)
                lines.append(f"password_file = {toml_scalar(pw_path)}")
            elif key == "api_key":
                api_path = write_setup_secret(secret_dir, f"{safe_section}-api-key", value)
                lines.append(f"api_key_file = {toml_scalar(api_path)}")
            elif key in {
                "user",
                "host",
                "hosts",
                "label",
                "url",
                "ssh_key_file",
                "api_key_file",
                "password_file",
                "scope",
                "api_key_only",
                "sudo_password_file",
            }:
                lines.append(f"{key} = {toml_scalar(value)}")
        lines.append("")
    if not lines:
        return ""
    path = os.path.join(secret_dir, "device-credentials.toml")
    with open(path, "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    os.chmod(path, 0o600)
    return path


def forbidden_browser_input(body):
    """Return the first browser-forbidden legacy field and error code."""
    if not isinstance(body, dict):
        return "", ""
    manual_fields = {
        "hosts_file",
        "hosts_import",
        "vm_contract",
        "owned_vmids",
        "template_vmids",
        "acknowledged_out_of_contract_vmids",
        "core_devices",
        "lab_devices",
        "subnet",
        "subnets",
        "toml",
    }

    def walk(value, prefix=""):
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key or "").strip().lower()
                field = f"{prefix}.{key}" if prefix else str(key)
                if normalized in manual_fields:
                    return field, "manual_contract_not_allowed"
                if normalized.endswith("_file") or normalized.endswith("_path"):
                    return field, "path_input_not_allowed"
                found = walk(nested, field)
                if found != ("", ""):
                    return found
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                found = walk(nested, f"{prefix}[{index}]")
                if found != ("", ""):
                    return found
        return "", ""

    field, code = walk(body)
    if field:
        return field, code
    return "", ""


def resolve_existing_secret_file(value, label):
    """Resolve one existing setup input without unnecessary escalation."""
    path = os.path.expanduser(str(value or "").strip())
    if not path:
        return ""

    def _sudo_file_exists(candidate):
        try:
            return subprocess.run(
                ["sudo", "-n", "test", "-f", candidate],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    if not os.path.isfile(path):
        candidate = legacy_init_input_candidate(path)
        if candidate and (os.path.isfile(candidate) or _sudo_file_exists(candidate)):
            path = candidate
    if not os.path.isfile(path) and not _sudo_file_exists(path):
        raise ValueError(f"{label} file not found: {path}")
    return path


def read_existing_secret_file(value, label):
    """Read one setup input, escalating only across a permission boundary."""
    path = resolve_existing_secret_file(value, label)
    if not path:
        return ""
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except PermissionError:
        result = subprocess.run(
            ["sudo", "-n", "cat", path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise PermissionError(f"{label} file is not readable: {path}")
        return result.stdout.strip()


def setup_init_command(cfg, body, job_id):
    secret_dir = setup_secret_dir(cfg, job_id)
    service_password = str(body.get("service_account_password") or body.get("password") or "").strip()
    dashboard_password = str(body.get("dashboard_password") or "").strip()
    bootstrap_password = str(body.get("bootstrap_password") or "").strip()
    pdm_password = str(body.get("pdm_password") or "").strip()
    service_password_file = resolve_existing_secret_file(
        body.get("service_account_password_file") or body.get("password_file"),
        "service_account_password",
    )
    dashboard_password_file = resolve_existing_secret_file(
        body.get("dashboard_password_file"), "dashboard_password"
    )
    bootstrap_password_file = resolve_existing_secret_file(
        body.get("bootstrap_password_file"), "bootstrap_password"
    )
    bootstrap_key_path = resolve_existing_secret_file(
        body.get("bootstrap_key_path") or body.get("bootstrap_key_file"),
        "bootstrap_key",
    )
    vm_contract_file = resolve_existing_secret_file(body.get("vm_contract"), "vm_contract")
    device_credentials_file = resolve_existing_secret_file(
        body.get("device_credentials_file"),
        "device_credentials",
    )
    if not service_password_file:
        if len(service_password) < 8:
            raise ValueError("service_account_password is required and must be at least 8 characters")
        service_password_file = write_setup_secret(
            secret_dir, "service-account-password", service_password
        )
    if body.get("dashboard_user") and not dashboard_password_file:
        if len(dashboard_password) < 8:
            raise ValueError("dashboard_password is required when dashboard_user is set")
        dashboard_password_file = write_setup_secret(
            secret_dir, "dashboard-password", dashboard_password
        )
    if bootstrap_password and not bootstrap_password_file:
        bootstrap_password_file = write_setup_secret(
            secret_dir, "bootstrap-password", bootstrap_password
        )
    pdm_password_file = write_setup_secret(secret_dir, "pdm-password", pdm_password)
    if not device_credentials_file:
        device_credentials_file = write_setup_device_credentials(
            secret_dir, body.get("device_credentials") or {}
        )

    code = "import sys; from freq.cli import main; raise SystemExit(main(sys.argv[1:]))"
    cmd = [
        sys.executable,
        "-c",
        code,
        "--yes",
        "init",
        "--headless",
        "--password-file",
        service_password_file,
    ]
    if body.get("bootstrap_user"):
        cmd.extend(["--bootstrap-user", str(body.get("bootstrap_user")).strip()])
    if bootstrap_password_file:
        cmd.extend(["--bootstrap-password-file", bootstrap_password_file])
    elif bootstrap_key_path:
        cmd.extend(["--bootstrap-key", bootstrap_key_path])
    elif body.get("bootstrap_key"):
        cmd.extend(["--bootstrap-key", os.path.expanduser(str(body.get("bootstrap_key")).strip())])
    if body.get("service_account"):
        cmd.extend(["--service-account", str(body.get("service_account")).strip()])
    if body.get("dashboard_user"):
        cmd.extend(["--dashboard-user", str(body.get("dashboard_user")).strip()])
    if dashboard_password_file:
        cmd.extend(["--dashboard-password-file", dashboard_password_file])
    pve_nodes = list_value(body.get("pve_nodes")) or list(getattr(cfg, "pve_nodes", []) or [])
    if pve_nodes:
        cmd.extend(["--pve-nodes", ",".join(pve_nodes)])
    pve_names = list_value(body.get("pve_node_names")) or list(
        getattr(cfg, "pve_node_names", []) or []
    )
    if pve_names:
        cmd.extend(["--pve-node-names", ",".join(pve_names)])
    for field, flag in (
        ("gateway", "--gateway"),
        ("nameserver", "--nameserver"),
        ("cluster_name", "--cluster-name"),
        ("ssh_mode", "--ssh-mode"),
        ("hosts_file", "--hosts-file"),
        ("owned_vmids", "--owned-vmids"),
        ("template_vmids", "--template-vmids"),
        ("acknowledged_out_of_contract_vmids", "--acknowledged-out-of-contract-vmids"),
        ("core_devices", "--core-devices"),
        ("lab_devices", "--lab-devices"),
        ("pdm_remote_name", "--pdm-remote-name"),
    ):
        if body.get(field):
            cmd.extend([flag, str(body.get(field)).strip()])
    if vm_contract_file:
        cmd.extend(["--vm-contract", vm_contract_file])
    if device_credentials_file:
        cmd.extend(["--device-credentials", device_credentials_file])
    if body.get("install_pdm"):
        cmd.append("--install-pdm")
    if body.get("skip_pdm"):
        cmd.append("--skip-pdm")
    if pdm_password_file:
        cmd.extend(["--pdm-pass", pdm_password_file])

    env = os.environ.copy()
    env["FREQ_DIR"] = cfg.install_dir
    env["FREQ_WEB_INIT"] = "1"
    env.setdefault("PYTHONUNBUFFERED", "1")
    if os.geteuid() != 0:
        cmd = [
            "sudo",
            "-n",
            "env",
            f"FREQ_DIR={cfg.install_dir}",
            "FREQ_WEB_INIT=1",
            "PYTHONUNBUFFERED=1",
        ] + cmd
    return cmd, env, secret_dir
