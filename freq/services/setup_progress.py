"""Normalize setup-init log lines and project phase progress."""

import datetime
import json
import os
import re
import signal
import subprocess
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from freq.core.setup_contract import SetupContractError
from freq.core.setup_state import SCHEMA as ZERO_STATE_WEB_SCHEMA
from freq.core.vault_key_input import _VaultKeyReadDuty
from freq.core.vault_decrypt_input import _VaultDecryptReadDuty
from freq.services.setup_inputs import _SetupInitDirectoryDuty, _SetupInitSecretFileDuty, _SetupBootstrapLookupDuty, _SetupInitVMContractDuty, _SetupDeviceMaterializationDuty


def redact_init_line(line, secret_dir):
    text = str(line or "").rstrip()
    if secret_dir:
        text = text.replace(secret_dir, "[setup-secret-dir]")
    return text


def parse_init_progress(line):
    match = re.search(r"Phase\s+(\d+)\s*(?:/|of)\s*(\d+)\s*[:—-]?\s*(.*)", str(line), re.I)
    if not match:
        return None
    current, total = int(match.group(1)), int(match.group(2))
    name = match.group(3).strip()[:120] or "Initialization"
    return {
        "phase": current,
        "phase_name": name,
        "current": current,
        "total": total,
        "message": f"Running {name}.",
    }


class SetupInitResetBusy(Exception):
    """Original reset occupancy refusal; response is outside state gates."""


def _setup_worker_first(first, later):
    if first is None or issubclass(type(first), Exception) and (
            not issubclass(type(later), Exception)
            or not issubclass(type(first), MemoryError)
            and issubclass(type(later), MemoryError)):
        return later
    return first


class _SetupInitPreparation:
    """Original pre-builder reservation; uncertainty never grants cleanup."""
    __slots__ = ('launch', 'job', 'cfg', 'request', 'contract', 'discovery',
                 'publication_stage', 'command_stage', 'command_result', 'args',
                 'setup_returned', 'failures', 'first_failures', 'failure', 'latest_failure',
                 'directory')

    def __init__(self, launch, cfg, request, contract, discovery):
        self.launch, self.job, self.cfg = launch, launch.job, cfg
        self.request, self.contract, self.discovery = request, contract, discovery
        self.publication_stage = 'pending'
        self.command_stage = 'unentered'
        self.command_result = self.args = None
        self.setup_returned = False
        self.failures = [None] * 4
        self.first_failures = [None] * 3
        self.failure = self.latest_failure = None
        self.directory = _SetupInitDirectoryDuty(launch, cfg)

    def remember(self, index, failure):
        # Root each boundary's first raw object before classifying. Also retain
        # first Control/Memory/ordinary across later errors at the same boundary.
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
        self.failure = _setup_worker_first(self.failure, failure)


def _setup_preparation_ready(launch):
    preparation = launch.preparation
    if preparation is None:
        # Preserve earlier private, already-prepared construction. The actual
        # start caller always attaches its new holder before job publication.
        return launch.preparation_required is False and launch.args is not None
    if type(preparation) is not _SetupInitPreparation:
        return False
    directory = preparation.directory
    service_file = directory.service_file if type(directory) is _SetupInitDirectoryDuty else None
    lookup = directory.bootstrap_lookup if type(directory) is _SetupInitDirectoryDuty else None
    bootstrap_file = directory.bootstrap_file if type(directory) is _SetupInitDirectoryDuty else None
    contract_file = directory.vm_contract if type(directory) is _SetupInitDirectoryDuty else None
    device = directory.device_credentials if type(directory) is _SetupInitDirectoryDuty else None
    pdm = directory.pdm_file if type(directory) is _SetupInitDirectoryDuty else None
    return (preparation.launch is launch and preparation.job is launch.job
            and launch.job.get('_worker_launch') is launch
            and preparation.publication_stage == 'returned'
            and preparation.command_stage == 'returned'
            and preparation.command_result is not None
            and preparation.args is launch.args and launch.args is not None
            and preparation.setup_returned is True
            and type(directory) is _SetupInitDirectoryDuty
            and directory.launch is launch and directory.job is launch.job
            and directory.cfg is preparation.cfg and directory.job_id == launch.job['id']
            and directory.used is True and directory.caller_returned is True
            and directory.mkdir_stage == 'returned'
            and directory.chmod_stage in ('returned', 'ignored')
            and directory.result_stage == 'stored' and directory.failure is None
            and directory.result_path is preparation.args[3]
            and type(service_file) is _SetupInitSecretFileDuty
            and service_file.directory is directory and service_file.launch is launch
            and service_file.job is launch.job and service_file.cfg is preparation.cfg
            and service_file.used is True and service_file.caller_returned is True
            and service_file.open_stage == 'returned' and service_file.handle is not None
            and service_file.enter_stage == 'returned'
            and service_file.entered_handle is service_file.handle
            and service_file.body_stage == 'returned' and service_file.exit_stage == 'returned'
            and service_file.mode_stage == 'returned' and service_file.result_stage == 'stored'
            and service_file.result_path is service_file.candidate_path
            and service_file.failure is None
            and type(lookup) is _SetupBootstrapLookupDuty
            and lookup.directory is directory and lookup.launch is launch
            and lookup.job is launch.job and lookup.cfg is preparation.cfg
            and lookup.setup_id == launch.job.get('setup_id')
            and lookup.setup_id == preparation.contract.get('setup_id')
            and lookup.setup_id is not None and lookup.cred_key == 'bootstrap_password'
            and lookup.used is True and lookup.stage == 'returned'
            and lookup.requested_host is not None and lookup.passed_empty_check is True
            and lookup.failure is None
            and type(lookup.key_read) is _VaultKeyReadDuty
            and lookup.key_read.lookup is lookup
            and lookup.key_read.directory is directory
            and lookup.key_read.launch is launch and lookup.key_read.job is launch.job
            and lookup.key_read.cfg is preparation.cfg and lookup.key_read.known()
            and type(lookup.decrypt_read) is _VaultDecryptReadDuty
            and lookup.decrypt_read.lookup is lookup
            and lookup.decrypt_read.key_read is lookup.key_read
            and lookup.decrypt_read.directory is directory
            and lookup.decrypt_read.launch is launch and lookup.decrypt_read.job is launch.job
            and lookup.decrypt_read.cfg is preparation.cfg and lookup.decrypt_read.known()
            and type(bootstrap_file) is _SetupInitSecretFileDuty
            and bootstrap_file.directory is directory and bootstrap_file.launch is launch
            and bootstrap_file.job is launch.job and bootstrap_file.cfg is preparation.cfg
            and bootstrap_file.name == 'bootstrap-password'
            and bootstrap_file.used is True and bootstrap_file.caller_returned is True
            and bootstrap_file.open_stage == 'returned' and bootstrap_file.handle is not None
            and bootstrap_file.enter_stage == 'returned'
            and bootstrap_file.entered_handle is bootstrap_file.handle
            and bootstrap_file.body_stage == 'returned' and bootstrap_file.exit_stage == 'returned'
            and bootstrap_file.mode_stage == 'returned' and bootstrap_file.result_stage == 'stored'
            and bootstrap_file.result_path is bootstrap_file.candidate_path
            and bootstrap_file.failure is None
            and type(contract_file) is _SetupInitVMContractDuty
            and contract_file.directory is directory and contract_file.launch is launch
            and contract_file.job is launch.job and contract_file.cfg is preparation.cfg
            and contract_file.name == 'vm-contract.toml' and contract_file.contract is preparation.contract
            and contract_file.used is True and contract_file.caller_returned is True
            and contract_file.format_stage == 'returned'
            and contract_file.open_stage == 'returned' and contract_file.handle is not None
            and contract_file.enter_stage == 'returned'
            and contract_file.entered_handle is contract_file.handle
            and contract_file.body_stage == 'returned' and contract_file.exit_stage == 'returned'
            and contract_file.mode_stage == 'returned' and contract_file.result_stage == 'stored'
            and contract_file.result_path is contract_file.candidate_path
            and contract_file.failure is None
            and type(device) is _SetupDeviceMaterializationDuty
            and device.directory is directory and device.launch is launch
            and device.job is launch.job and device.cfg is preparation.cfg
            and device.contract is preparation.contract
            and device.setup_id == launch.job.get('setup_id')
            and device.used is True and device.caller_returned is True
            and device.stage == 'returned' and device.gate is not None
            and device.entry_stage == 'returned' and device.gate_stage == 'returned'
            and device.body_stage == 'returned' and device.result_stage == 'stored'
            and device.failure is None
            and type(pdm) is _SetupInitSecretFileDuty
            and pdm.directory is directory and pdm.launch is launch
            and pdm.job is launch.job and pdm.cfg is preparation.cfg and pdm.name == 'pdm-password'
            and pdm.pdm_mode == preparation.request.get('pdm_mode')
            and pdm.used is True and pdm.caller_returned is True and pdm.failure is None
            and ((pdm.pdm_mode == 'skip' and pdm.result_stage == 'empty' and pdm.result_path == ''
                and pdm.open_stage == 'unused' and pdm.handle is None and pdm.enter_stage == 'unused'
                and pdm.body_stage == 'unused' and pdm.exit_stage == 'unused' and pdm.mode_stage == 'unused')
                or (pdm.pdm_mode == 'install' and pdm.result_stage == 'stored'
                and pdm.open_stage == 'returned' and pdm.handle is not None
                and pdm.enter_stage == 'returned' and pdm.entered_handle is pdm.handle
                and pdm.body_stage == 'returned' and pdm.exit_stage == 'returned'
                and pdm.mode_stage == 'returned' and pdm.result_path is pdm.candidate_path))
            and preparation.failure is None
            and all(failure is None for failure in preparation.failures))


class _SetupInitWorkerLaunch:
    """Original job-rooted launch storage, never a thread/child closure proof.

    The original start caller attaches this pure holder before publishing the
    same job and before factory/start. Unknown calls retain this exact holder,
    its worker if returned, and adapter responsibility. No retry or implicit
    directory cleanup is available. This first stage deliberately has no
    settlement/recovery method; known successful start is not thread closure.
    """
    __slots__ = ('job', 'target', 'args', 'worker', 'stage', 'used',
                 'failures', 'failure', 'job_report_stage', 'state_report_stage', 'child', 'settlement', 'cancellation',
                 'prep_stage', 'prep_failures', 'prep_failure',
                 'prep_cleanup_stage', 'prep_report_stage', 'preparation',
                 'preparation_required', 'claim_body_failure', 'claim_context_failure',
                 'job_report_body_failure')

    def __init__(self, job, target, args):
        self.job, self.target, self.args = job, target, args
        self.worker = None
        self.child = None
        self.preparation = None
        self.preparation_required = args is None
        self.settlement = None
        self.cancellation = None
        self.stage, self.used = 'prepared', False
        self.failures = [None] * 3
        self.failure = None
        self.claim_body_failure = self.claim_context_failure = None
        self.job_report_body_failure = None
        self.job_report_stage = self.state_report_stage = 'unused'
        self.prep_stage = self.prep_cleanup_stage = self.prep_report_stage = 'unused'
        self.prep_failures = [None] * 4
        self.prep_failure = None

    def launch(self, cfg, runtime):
        if (self.used or self.prep_stage != 'unused'
                or not _setup_preparation_ready(self)
                or self.preparation is not None and self.preparation.cfg is not cfg):
            raise SetupContractError('init_start_failed', 'Setup init worker could not start.', status=500)
        self.used = True
        self.stage = 'claim-pending'
        try:
            try:
                with runtime.init_lock():
                    try:
                        if (runtime.current_job() is not self.job
                                or self.job.get('_worker_launch') is not self):
                            raise SetupContractError('init_start_failed', 'Setup init worker could not start.', status=500)
                    except BaseException as failure:
                        # Retain the raw body before the original gate exits.
                        self.claim_body_failure = failure
                        raise
            except BaseException as failure:
                # This may be the body's rethrow, not a separate exit failure.
                self.claim_context_failure = failure
            self.failure = self.claim_body_failure
            if self.claim_context_failure is not None:
                self.failure = _setup_worker_first(self.failure, self.claim_context_failure)
            if self.failure is not None:
                raise self.failure from None
            self.stage = 'factory-pending'
            worker = runtime.worker_factory(
                target=self.target, args=self.args, daemon=True,
                name=f"freq-setup-init-{self.job['id']}")
            self.worker = worker
            self.stage = 'factory-returned'
            self.stage = 'start-pending'
            worker.start()
            self.stage = 'start-returned'
            return
        except BaseException as failure:
            self.failures[0] = self.failure = failure
        # A factory/start error is not proof of no worker. Do not remove
        # adapters, discard the original handle, retry, or clear the job.
        self.job_report_stage = 'pending'
        try:
            with runtime.init_lock():
                try:
                    if (runtime.current_job() is not self.job
                            or self.job.get('_worker_launch') is not self):
                        raise SetupContractError('init_start_failed', 'Setup init worker could not start.', status=500)
                    self.job['state'] = 'failed'
                    self.job['error'] = 'setup init worker could not start'
                except BaseException as failure:
                    self.job_report_body_failure = failure
                    raise
        except BaseException as failure:
            self.failures[1] = failure
        else:
            if self.job_report_body_failure is None:
                self.job_report_stage = 'returned'
        self.state_report_stage = 'pending'
        try:
            runtime.update_state(cfg, phase='blocked', last_error_code='init_start_failed')
        except BaseException as failure:
            self.failures[2] = failure
        else:
            self.state_report_stage = 'returned'
        if self.job_report_body_failure is not None:
            self.failure = _setup_worker_first(self.failure, self.job_report_body_failure)
        for index in (1, 2):
            failure = self.failures[index]
            if failure is not None:
                self.failure = _setup_worker_first(self.failure, failure)
        if (not issubclass(type(self.failure), Exception)
                or issubclass(type(self.failure), MemoryError)):
            raise self.failure from None
        raise SetupContractError('init_start_failed', 'Setup init worker could not start.', status=500) from None


_SETUP_INIT_LINE_CHAR_LIMIT = 16384
_SETUP_INIT_TOTAL_CHAR_LIMIT = 4194304


class _SetupInitChildDuty:
    """One original worker's retained child, output and adapter obligations.

    No settlement here releases the launch slot. Pending calls remain unknown;
    failure cleanup never introduces a new wait or retries a consumed operation.
    """
    __slots__ = ('launch', 'job', 'process', 'stream', 'process_stage',
                 'publication_stage', 'stream_stage', 'read_stage', 'wait_stage',
                 'adapter_stage', 'returncode', 'failures', 'failure_count', 'failure',
                 'completion_stage', 'cancel_process_ready', 'cancel_publish_stage',
                 'output_read_stage', 'output_chars')

    def __init__(self, launch):
        self.launch, self.job = launch, launch.job
        self.process = self.stream = None
        self.process_stage = self.publication_stage = 'unused'
        self.stream_stage = self.read_stage = self.wait_stage = 'unused'
        self.adapter_stage = 'unused'
        self.completion_stage = 'pending'
        self.output_read_stage = 'unused'
        self.output_chars = 0
        self.cancel_process_ready = False
        self.cancel_publish_stage = 'unused'
        self.returncode = None
        self.failures = [None] * 16
        self.failure_count = 0
        self.failure = None

    def remember(self, failure):
        # Fixed capacity bounds this caller's independent error sites.
        # Store raw identity before any classification or error reporting.
        self.failures[self.failure_count] = failure
        self.failure_count += 1

    def spawn(self, runtime):
        if self.process_stage != 'unused':
            raise SetupContractError('init_failed', 'Setup init worker failed.', status=500)
        args = self.launch.args
        cwd = args[2].get('FREQ_DIR') or None
        self.process_stage = 'pending'
        process = runtime.popen(args[1], cwd=cwd, env=args[2],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.process = process
        self.process_stage = 'returned'
        self.publication_stage = 'pending'
        if runtime.publish_process(args[0], process) is not True:
            raise SetupContractError('init_failed', 'Setup init worker failed.', status=500)
        self.publication_stage = 'returned'
        self.stream_stage = 'lookup-pending'
        self.stream = process.stdout
        self.stream_stage = 'absent' if self.stream is None else 'open'
        return process

    def next_output_line(self):
        """Acquire one bounded decoded line, never retry an unknown read."""
        if (self.stream_stage != 'open'
                or self.output_read_stage not in ('unused', 'returned')):
            raise SetupContractError('init_failed', 'Setup init output is unavailable.', status=500)
        remaining = _SETUP_INIT_TOTAL_CHAR_LIMIT - self.output_chars
        if remaining < 0:
            raise SetupContractError('init_failed', 'Setup init output is unavailable.', status=500)
        limit = min(_SETUP_INIT_LINE_CHAR_LIMIT, remaining)
        self.output_read_stage = 'pending'
        line = self.stream.readline(limit + 1)
        if type(line) is not str:
            raise SetupContractError('init_failed', 'Setup init output is unavailable.', status=500)
        self.output_chars += len(line)
        if len(line) > limit:
            raise SetupContractError('init_failed', 'Setup init output exceeds the application limit.', status=500)
        if line == '':
            self.output_read_stage = 'eof'
            return None
        self.output_read_stage = 'returned'
        return line

    def wait(self):
        if self.process_stage != 'returned' or self.wait_stage != 'unused':
            raise SetupContractError('init_failed', 'Setup init worker failed.', status=500)
        self.wait_stage = 'pending'
        self.returncode = self.process.wait()
        self.wait_stage = 'returned'
        return self.returncode

    def close_output(self):
        if self.stream_stage != 'open':
            return
        self.stream_stage = 'close-pending'
        self.stream.close()
        self.stream_stage = 'closed'

    def cleanup_adapters(self, runtime):
        if (self.wait_stage != 'returned'
                or self.stream_stage not in ('closed', 'absent')
                or self.adapter_stage != 'unused'):
            return False
        secret_dir = self.launch.args[3]
        self.adapter_stage = 'remove-pending'
        try:
            runtime.remove_tree(secret_dir)
        except FileNotFoundError:
            pass
        self.adapter_stage = 'verify-pending'
        if os.path.exists(secret_dir):
            raise OSError('transient init adapters remain')
        self.adapter_stage = 'returned'
        return True

    def selected_failure(self):
        first = None
        index = 0
        while index < self.failure_count:
            first = _setup_worker_first(first, self.failures[index])
            index += 1
        self.failure = first
        return first


def _bind_setup_init_child(job_id, cmd, env, secret_dir, setup_id, runtime):
    """Bind actual thread/arguments to the original launch before child entry."""
    worker = threading.current_thread()
    with runtime.init_lock:
        job = runtime.current_job()
        launch = job.get('_worker_launch') if job else None
        if (type(launch) is not _SetupInitWorkerLaunch
                or launch.job is not job or launch.worker is not worker
                or launch.stage not in ('start-pending', 'start-returned')
                or launch.child is not None
                or launch.args[0] is not job_id or launch.args[1] is not cmd
                or launch.args[2] is not env or launch.args[3] is not secret_dir
                or launch.args[4] is not setup_id):
            raise SetupContractError('init_failed', 'Setup init worker failed.', status=500)
        child = _SetupInitChildDuty(launch)
        launch.child = child
        return child


class _SetupInitWorkerSettlement:
    """Original exact-thread observation duty; unknown outcomes never retry."""
    __slots__ = ('launch', 'child', 'worker', 'stage', 'failure',
                 'first_failures', 'latest_failure', 'lock_body_failures',
                 'lock_context_failures')
    def __init__(self, launch):
        self.launch, self.child, self.worker = launch, launch.child, launch.worker
        self.stage, self.failure = 'prepared', None
        self.first_failures = [None, None, None]
        self.latest_failure = None
        self.lock_body_failures = [None] * 3
        self.lock_context_failures = [None] * 3

    def remember(self, failure):
        # Preserve the new raw object before classifying. Original first errors
        # remain in fixed Control/Memory/ordinary slots across explicit requests.
        self.latest_failure = failure
        if not issubclass(type(failure), Exception):
            index = 0
        elif issubclass(type(failure), MemoryError):
            index = 1
        else:
            index = 2
        if self.first_failures[index] is None:
            self.first_failures[index] = failure
        self.failure = _setup_worker_first(self.failure, failure)



def _setup_init_child_complete(launch):
    child = launch.child
    return (_setup_preparation_ready(launch)
            and launch.prep_stage == 'unused' and launch.prep_failure is None
            and type(child) is _SetupInitChildDuty and child.launch is launch
            and child.job is launch.job and child.completion_stage == 'returned'
            and child.failure_count == 0 and child.process_stage == 'returned'
            and child.publication_stage == 'returned' and child.read_stage == 'returned'
            and child.wait_stage == 'returned' and child.adapter_stage == 'returned'
            and child.stream_stage in ('closed', 'absent')
            and _setup_cancellation_complete(launch))


def _setup_init_settlement_current(runtime, duty):
    launch = duty.launch
    return (runtime.current_job() is launch.job
            and launch.job.get('_worker_launch') is launch
            and launch.settlement is duty and launch.child is duty.child
            and launch.worker is duty.worker and launch.stage == 'start-returned'
            and launch.failure is None
            and _setup_init_child_complete(launch))


def settle_setup_init_launch(*, runtime):
    """Observe only fully known normal completion outside original state gates.

    This is called by an explicit original request, never a snapshot, timer,
    background poll or unknown-launch recovery. A known live thread defers join;
    one failed observation/join retains its exact duty and prevents another call.
    """
    duty = None
    body_failure = None
    lock_index = 0
    context_pending = False
    try:
        context_pending = True
        with runtime.current_lock():
            try:
                job = runtime.current_job()
                launch = job.get('_worker_launch') if job else None
                if type(launch) is not _SetupInitWorkerLaunch or launch.job is not job:
                    return False
                existing = launch.settlement
                if type(existing) is _SetupInitWorkerSettlement and existing.launch is launch:
                    duty = existing
                if (launch.stage != 'start-returned' or launch.failure is not None
                        or not _setup_init_child_complete(launch)):
                    return False
                if duty is None:
                    if existing is not None:
                        return False
                    duty = _SetupInitWorkerSettlement(launch)
                    launch.settlement = duty
                if (type(duty) is not _SetupInitWorkerSettlement
                        or not _setup_init_settlement_current(runtime, duty)
                        or duty.failure is not None or duty.stage not in ('prepared', 'alive')):
                    return False
                duty.stage = 'observe-pending'
            except BaseException as failure:
                # Capture before the original context can replace the raw body.
                body_failure = failure
                if duty is not None and type(duty) is _SetupInitWorkerSettlement:
                    duty.lock_body_failures[lock_index] = failure
                raise
        context_pending = False
        if body_failure is not None:
            raise body_failure from None
        alive = duty.worker.is_alive()
        if alive is True:
            lock_index = 1
            context_pending = True
            with runtime.current_lock():
                try:
                    if not _setup_init_settlement_current(runtime, duty):
                        return False
                    duty.stage = 'alive-release-pending'
                except BaseException as failure:
                    # Capture before the original context can replace the raw body.
                    body_failure = failure
                    if duty is not None and type(duty) is _SetupInitWorkerSettlement:
                        duty.lock_body_failures[lock_index] = failure
                    raise
            context_pending = False
            if body_failure is not None:
                raise body_failure from None
            duty.stage = 'alive'
            return False
        if alive is not False:
            raise SetupContractError('init_running', 'Setup init is still occupied.', status=409)
        duty.stage = 'join-pending'
        if duty.worker.join(timeout=0) is not None:
            raise SetupContractError('init_running', 'Setup init is still occupied.', status=409)
        duty.stage = 'join-returned'
        duty.stage = 'final-observe-pending'
        if duty.worker.is_alive() is not False:
            duty.stage = 'unconfirmed'
            return False
        duty.stage = 'revalidate-pending'
        lock_index = 2
        context_pending = True
        with runtime.current_lock():
            try:
                if not _setup_init_settlement_current(runtime, duty):
                    return False
                # Occupancy also requires known returned lock release below. A
                # thread-closed label alone never grants admission/reset.
                duty.stage = 'commit-pending'
                duty.launch.stage = 'thread-closed'
            except BaseException as failure:
                # Capture before the original context can replace the raw body.
                body_failure = failure
                if duty is not None and type(duty) is _SetupInitWorkerSettlement:
                    duty.lock_body_failures[lock_index] = failure
                raise
        context_pending = False
        if body_failure is not None:
            raise body_failure from None
        duty.stage = 'closed'
        return True
    except BaseException as failure:
        if duty is not None and type(duty) is _SetupInitWorkerSettlement:
            # Keep the escaping context outcome separate. It may be the same
            # raw body rethrow, rather than a distinct native exit failure.
            if context_pending:
                duty.lock_context_failures[lock_index] = failure
            if body_failure is not None:
                duty.remember(body_failure)
            duty.remember(failure)
            failure = duty.failure
        elif body_failure is not None:
            # A failure before selecting an original duty grants no new owner.
            failure = _setup_worker_first(body_failure, failure)
        if (not issubclass(type(failure), Exception)
                or issubclass(type(failure), MemoryError)):
            raise failure from None
        return False


class _SetupInitCancelDuty:
    """One original job's signal intent, never a delivery/closure receipt."""
    __slots__ = ('launch', 'job', 'child', 'process', 'used', 'stage',
                 'native_returned', 'admission_returned', 'report_stage', 'first_failures',
                 'latest_failure', 'failure')

    def __init__(self, launch):
        self.launch, self.job = launch, launch.job
        self.child = self.process = None
        self.used, self.native_returned = False, False
        self.admission_returned = False
        self.stage, self.report_stage = 'queued', 'unused'
        self.first_failures = [None, None, None]
        self.latest_failure = self.failure = None

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
        self.failure = _setup_worker_first(self.failure, failure)
        self.stage = 'unknown'

    def refuse_unknown(self):
        first = self.failure
        if first is not None and (not issubclass(type(first), Exception)
                                 or issubclass(type(first), MemoryError)):
            raise first from None
        raise SetupContractError('init_cancel_delivery_unknown',
            'Init cancellation outcome is unknown.', status=503) from None


def _setup_cancel_launch(job):
    launch = job.get('_worker_launch') if job else None
    if type(launch) is _SetupInitWorkerLaunch and launch.job is job:
        return launch
    return None


def _setup_cancel_duty(job, *, create=False):
    """Pure original state helper; acquiring callers hold the original init gate."""
    launch = _setup_cancel_launch(job)
    if launch is None:
        raise SetupContractError('init_cancel_delivery_unknown',
            'Init cancellation outcome is unknown.', status=503)
    duty = launch.cancellation
    if duty is None:
        # Intent is rooted first. Allocation/return loss cannot later turn a
        # requested legacy record into permission to construct and send again.
        if not create or job.get('cancel_requested') is True:
            raise SetupContractError('init_cancel_delivery_unknown',
                'Init cancellation outcome is unknown.', status=503)
        job['cancel_requested'] = True
        duty = _SetupInitCancelDuty(launch)
        launch.cancellation = duty
    if (type(duty) is not _SetupInitCancelDuty or duty.launch is not launch
            or duty.job is not job):
        raise SetupContractError('init_cancel_delivery_unknown',
            'Init cancellation outcome is unknown.', status=503)
    return duty


def _setup_cancel_process(duty, process):
    """Bind only the child/process already retained by the original launcher."""
    child = duty.launch.child
    if (type(child) is not _SetupInitChildDuty or child.launch is not duty.launch
            or child.job is not duty.job or child.process is not process
            or child.process_stage != 'returned'
            or child.cancel_process_ready is not True):
        duty.refuse_unknown()
    if duty.process is None and not duty.used and duty.failure is None:
        duty.child, duty.process = child, process
    if duty.child is not child or duty.process is not process:
        duty.refuse_unknown()


def _setup_cancellation_complete(launch):
    duty = launch.cancellation
    if duty is None:
        return launch.job.get('cancel_requested') is not True
    child = launch.child
    return (type(duty) is _SetupInitCancelDuty and duty.launch is launch
            and duty.job is launch.job and type(child) is _SetupInitChildDuty
            and duty.child is child and duty.process is child.process
            and duty.stage == 'returned' and duty.admission_returned is True
            and duty.native_returned is True
            and duty.report_stage == 'returned' and duty.failure is None)


def _setup_cancel_projection(job):
    """Presentation only; detached values never authorize another signal."""
    launch = _setup_cancel_launch(job)
    if launch is None:
        requested = job.get('cancel_requested') is True if job else False
        delivery = job.get('_cancel_delivery') if job else None
        if delivery not in ('not_requested', 'pending', 'sent', 'unknown'):
            delivery = 'unknown'
        if delivery == 'not_requested' and requested:
            delivery = 'unknown'
        if delivery in ('pending', 'sent') and not requested:
            delivery = 'unknown'
        return requested, delivery
    duty = launch.cancellation
    if duty is None:
        requested = job.get('cancel_requested') is True
        return requested, 'unknown' if requested else 'not_requested'
    if type(duty) is not _SetupInitCancelDuty or duty.launch is not launch or duty.job is not job:
        return job.get('cancel_requested') is True, 'unknown'
    if (duty.stage == 'queued' and duty.admission_returned is True
            and not duty.used and duty.failure is None):
        return True, 'pending'
    if _setup_cancellation_complete(launch):
        return True, 'sent'
    return True, 'unknown'


def _setup_worker_launch_unsettled(job):
    """Negative occupancy only. Detached DATA never permits live admission."""
    if not job:
        return False
    if '_worker_launch' in job:
        duty = job['_worker_launch']
        return (type(duty) is not _SetupInitWorkerLaunch or duty.job is not job
                or not _setup_preparation_ready(duty)
                or duty.prep_stage != 'unused' or duty.prep_failure is not None
                or duty.stage != 'thread-closed'
                or type(duty.settlement) is not _SetupInitWorkerSettlement
                or duty.settlement.launch is not duty
                or duty.settlement.child is not duty.child
                or duty.settlement.worker is not duty.worker
                or duty.settlement.stage != 'closed'
                or duty.settlement.failure is not None
                or not _setup_cancellation_complete(duty))
    return job.get('_launch_unsettled') is True


def project_init_job(job, *, log_limit=100):
    lines = list((job or {}).get("lines") or [])[-log_limit:] if log_limit else []
    job_state = (job or {}).get("state", "queued")
    launch_unsettled = _setup_worker_launch_unsettled(job)
    cancel_requested, cancel_delivery = _setup_cancel_projection(job)
    payload = {
        "id": (job or {}).get("id"),
        "state": job_state,
        "returncode": (job or {}).get("returncode"),
        "initialized": bool((job or {}).get("initialized")),
        "web_setup_complete": bool((job or {}).get("web_setup_complete")),
        "poll_after_ms": 0 if (job or {}).get("state") in {"succeeded", "failed"} else 1000,
        "progress": dict((job or {}).get("progress") or {}),
        "log_tail": lines,
        "cancellation": {
            "requested": cancel_requested,
            "delivery": cancel_delivery,
            "retryable": False,
        },
    }
    if (job or {}).get("state") == "failed":
        payload["error"] = {
            "code": "init_failed",
            "message": (job or {}).get("error") or "Setup initialization failed.",
            "retryable": not launch_unsettled,
        }
    return payload


def project_discovery_job(job):
    payload = {
        "id": job.get("id"),
        "state": job.get("state", "queued"),
        "started_at": job.get("started_at"),
        "updated_at": job.get("updated_at"),
        "finished_at": job.get("finished_at"),
        "poll_after_ms": job.get("poll_after_ms", 1000),
        "progress": dict(job.get("progress") or {}),
    }
    if job.get("state") == "succeeded":
        payload["results"] = json.loads(json.dumps(job.get("results") or {}))
    if job.get("state") == "failed":
        payload["error"] = dict(job.get("error") or {})
    return payload


def snapshot_init_job(init_job):
    if not init_job:
        return {"running": False, "job": None}
    launch_unsettled = _setup_worker_launch_unsettled(init_job)
    cancel_requested, cancel_delivery = _setup_cancel_projection(init_job)
    job = dict(init_job)
    job.pop("process", None)
    job.pop("_worker_launch", None)
    job["_launch_unsettled"] = launch_unsettled
    job["cancel_requested"] = cancel_requested
    job["_cancel_delivery"] = cancel_delivery
    job["lines"] = list(init_job.get("lines", []))[-300:]
    return {"running": launch_unsettled or job.get("state") in {"queued", "running"}, "job": job}


def snapshot_live_init_job(*, current_lock, current_job):
    """Project the current dashboard job while holding its live owner lock."""
    with current_lock():
        return snapshot_init_job(current_job())


def snapshot_discovery_job(discovery_job):
    """Return one isolated internal discovery snapshot."""
    if not discovery_job:
        return None
    return json.loads(json.dumps(discovery_job))


def snapshot_live_discovery_job(*, current_lock, current_job):
    """Snapshot the current discovery job while holding its live owner lock."""
    with current_lock():
        return snapshot_discovery_job(current_job())


@dataclass(frozen=True)
class SetupInitStatusRuntime:
    """Dashboard-owned readers required by init-status resolution."""

    snapshot_job: Callable[[], dict]
    observe_state: Callable[[Any], dict]


@dataclass(frozen=True)
class SetupInitStatusResolution:
    """Transport-free classification of one owner-bound init status lookup."""

    kind: str
    job: dict | None


def resolve_setup_init_status(
    cfg,
    job_id,
    owner,
    *,
    runtime: SetupInitStatusRuntime,
):
    """Resolve one current init snapshot without performing HTTP transport."""
    snapshot = runtime.snapshot_job()
    job = snapshot.get("job")
    state = runtime.observe_state(cfg)
    if not job:
        kind = "expired" if state.get("active_init_job_id") == job_id else "absent"
        return SetupInitStatusResolution(kind=kind, job=None)
    if job.get("id") != job_id or job.get("owner") != owner:
        return SetupInitStatusResolution(kind="not_found", job=None)
    return SetupInitStatusResolution(kind="found", job=job)


@dataclass(frozen=True)
class SetupInitLogsRuntime:
    """Dashboard-owned reader required by init-log resolution."""

    snapshot_job: Callable[[], dict]


@dataclass(frozen=True)
class SetupInitLogsResolution:
    """Transport-free result of one owner-bound init-log lookup."""

    kind: str
    job: dict | None


def resolve_setup_init_logs(
    job_id,
    owner,
    *,
    runtime: SetupInitLogsRuntime,
):
    """Resolve one current owner-bound init-log snapshot."""
    snapshot = runtime.snapshot_job()
    job = snapshot.get("job")
    if not job or job.get("id") != job_id or job.get("owner") != owner:
        return SetupInitLogsResolution(kind="not_found", job=None)
    return SetupInitLogsResolution(kind="found", job=job)


@dataclass(frozen=True)
class SetupDiscoveryStatusResolution:
    """Pure setup-discovery status lookup result."""

    kind: str
    job: dict | None


def resolve_setup_discovery_status(state, job_id, job):
    """Classify one setup-bound discovery snapshot without exposing it."""
    if not job:
        kind = "expired" if state.get("active_discovery_id") == job_id else "absent"
        return SetupDiscoveryStatusResolution(kind=kind, job=None)
    if job.get("id") != job_id or job.get("setup_id") != state.get("setup_id"):
        return SetupDiscoveryStatusResolution(kind="not_found", job=None)
    return SetupDiscoveryStatusResolution(kind="found", job=job)


@dataclass(frozen=True)
class SetupContractGetResolution:
    """Pure transport decision for one setup-contract GET request."""

    kind: str
    contract: dict | None
    getter: Callable[[str], Any] | None


def resolve_setup_contract_get(
    cfg,
    state,
    *,
    load_contract,
    build_getter,
):
    """Resolve the active setup contract without transport effects."""
    contract = load_contract(cfg)
    if (
        not contract
        or contract.get("setup_id") != state.get("setup_id")
        or contract.get("contract_id") != state.get("active_contract_id")
    ):
        return SetupContractGetResolution(kind="not_found", contract=None, getter=None)
    getter = build_getter(cfg, state["setup_id"])
    return SetupContractGetResolution(
        kind="found",
        contract=contract,
        getter=getter,
    )


@dataclass(frozen=True)
class SetupContractAdmissionResult:
    """Transport-free result of one setup-contract POST admission."""

    contract: dict
    payload: dict
    replay: bool


@dataclass(frozen=True)
class SetupContractAdmissionRuntime:
    """Dashboard-owned state and effects required by contract admission."""

    setup_lock: Callable[[], Any]
    observe_state: Callable[..., dict | None]
    snapshot_discovery: Callable[[], dict | None]
    load_contract: Callable[..., dict]
    retire_contract: Callable[..., Any]
    build_contract: Callable[..., dict]
    credential_keys: Callable[[dict], list[str]]
    vault_host: Callable[[str], str]
    vault_list: Callable[..., list]
    vault_update: Callable[..., bool]
    save_contract: Callable[..., Any]
    clear_contract: Callable[..., Any]
    build_getter: Callable[..., Callable[[str], Any]]
    project_contract: Callable[[dict, Callable[[str], Any]], dict]
    update_state: Callable[..., Any]


def admit_setup_contract(
    cfg,
    body,
    owner,
    *,
    runtime: SetupContractAdmissionRuntime,
):
    """Atomically replay or persist one owner-bound setup contract."""
    with runtime.setup_lock():
        state = runtime.observe_state(cfg)
        if not state:
            raise SetupContractError("setup_expired", "The setup window expired.", status=410)
        if state.get("username") != owner:
            raise SetupContractError(
                "setup_owner_mismatch",
                "Setup belongs to another operator.",
                status=403,
            )
        discovery = runtime.snapshot_discovery()
        if (
            not discovery
            or discovery.get("state") != "succeeded"
            or discovery.get("id") != state.get("active_discovery_id")
        ):
            raise SetupContractError(
                "stale_discovery",
                "A current successful discovery is required.",
                "discovery_id",
                409,
            )
        previous = runtime.load_contract(cfg)
        if previous and (
            previous.get("setup_id") != state.get("setup_id")
            or previous.get("discovery_id") != discovery.get("id")
        ):
            runtime.retire_contract(cfg, previous)
            previous = {}
        request_id = str(body.get("client_request_id") or "").strip()
        replay = bool(
            previous
            and request_id
            and previous.get("client_request_id") == request_id
            and previous.get("setup_id") == state.get("setup_id")
            and previous.get("discovery_id") == discovery.get("id")
            and body.get("schema") == ZERO_STATE_WEB_SCHEMA
            and body.get("setup_id") == state.get("setup_id")
            and body.get("discovery_id") == discovery.get("id")
        )
        stale_values = {}
        if replay:
            contract = previous
        else:
            contract = runtime.build_contract(
                body,
                discovery,
                setup_id=state["setup_id"],
                previous=previous,
            )
            keep_keys = set(runtime.credential_keys(contract))
            stale_keys = [
                key for key in runtime.credential_keys(previous) if key not in keep_keys
            ]
            host = runtime.vault_host(state["setup_id"])
            exact_values = {
                key: value
                for entry_host, key, value in runtime.vault_list(cfg)
                if entry_host == host
            }
            stale_values = {key: exact_values[key] for key in stale_keys if key in exact_values}
            if stale_values and not runtime.vault_update(
                cfg,
                host,
                {key: None for key in stale_values},
            ):
                raise SetupContractError(
                    "credential_cleanup_failed",
                    "Stale setup credentials could not be removed.",
                    status=500,
                )
        try:
            if not replay:
                runtime.save_contract(cfg, contract)
            getter = runtime.build_getter(cfg, state["setup_id"])
            payload = runtime.project_contract(contract, getter)
            if not replay:
                runtime.update_state(
                    cfg,
                    phase="ready" if payload["ready"] else "credentials",
                    active_contract_id=contract["contract_id"],
                    last_error_code=None,
                )
        except Exception:
            if not replay:
                if stale_values:
                    runtime.vault_update(cfg, host, stale_values)
                if previous:
                    runtime.save_contract(cfg, previous)
                else:
                    runtime.clear_contract(cfg)
            raise
    return SetupContractAdmissionResult(
        contract=contract,
        payload=payload,
        replay=replay,
    )


@dataclass(frozen=True)
class SetupDeviceCredentialAdmissionResult:
    """Transport-free result of one device-credential admission."""

    contract: dict
    presence: list[dict]
    ready: bool
    replay: bool


@dataclass(frozen=True)
class SetupDeviceCredentialAdmissionRuntime:
    """Dashboard-owned state and effects required by credential admission."""

    setup_lock: Callable[[], Any]
    load_state: Callable[..., dict | None]
    load_contract: Callable[..., dict]
    validate_request: Callable[..., dict]
    vault_exists: Callable[[str], bool]
    vault_init: Callable[..., bool]
    vault_host: Callable[[str], str]
    vault_list: Callable[..., list]
    vault_update: Callable[..., bool]
    credential_key: Callable[[str, str], str]
    storage_value: Callable[[str, Any], Any]
    record_request: Callable[[dict, str], Any]
    save_contract: Callable[..., Any]
    build_getter: Callable[..., Callable[[str], Any]]
    project_presence: Callable[[dict, Callable[[str], Any]], list[dict]]
    update_state: Callable[..., Any]


def admit_setup_device_credentials(
    cfg,
    body,
    owner,
    *,
    runtime: SetupDeviceCredentialAdmissionRuntime,
):
    """Atomically replay or persist one owner-bound credential request."""
    with runtime.setup_lock():
        state = runtime.load_state(cfg)
        contract = runtime.load_contract(cfg)
        if not state:
            raise SetupContractError("setup_expired", "The setup window expired.", status=410)
        if state.get("username") != owner:
            raise SetupContractError(
                "setup_owner_mismatch",
                "Setup belongs to another operator.",
                status=403,
            )
        if (
            not contract
            or contract.get("setup_id") != state.get("setup_id")
            or contract.get("contract_id") != state.get("active_contract_id")
        ):
            raise SetupContractError(
                "stale_contract",
                "A current selection contract is required.",
                "contract_id",
                409,
            )
        request = runtime.validate_request(body, contract, state["setup_id"])
        request_id = request["client_request_id"]
        replay = bool(
            request_id and request_id in (contract.get("credential_request_ids") or [])
        )
        host = runtime.vault_host(state["setup_id"])

        def publish_presence():
            getter = runtime.build_getter(cfg, state["setup_id"])
            presence = runtime.project_presence(contract, getter)
            ready = all(row["complete"] for row in presence)
            runtime.update_state(
                cfg,
                phase="ready" if ready else "credentials",
                active_contract_id=contract["contract_id"],
                last_error_code=None,
            )
            return presence, ready

        if replay:
            presence, ready = publish_presence()
        else:
            if not runtime.vault_exists(cfg.vault_file) and not runtime.vault_init(cfg):
                raise SetupContractError(
                    "credential_store_failed",
                    "The setup vault could not be initialized.",
                    status=500,
                )
            updates = {}
            for row in request["credentials"]:
                for field in row.get("clear_fields") or []:
                    key = runtime.credential_key(row["resource_id"], field)
                    updates[key] = None
                for field, value in row["values"].items():
                    key = runtime.credential_key(row["resource_id"], field)
                    updates[key] = runtime.storage_value(field, value)
            before_values = {
                key: value
                for entry_host, key, value in runtime.vault_list(cfg)
                if entry_host == host
            }
            originals = {
                key: before_values[key] if key in before_values else None for key in updates
            }
            original_contract = json.loads(json.dumps(contract))
            try:
                if updates and not runtime.vault_update(cfg, host, updates):
                    raise OSError("vault write failed")
                exact_values = {
                    key: value
                    for entry_host, key, value in runtime.vault_list(cfg)
                    if entry_host == host
                }
                if any(exact_values.get(key) != value for key, value in updates.items()):
                    raise OSError("vault verification failed")
                runtime.record_request(contract, request_id)
                runtime.save_contract(cfg, contract)
                presence, ready = publish_presence()
            except Exception:
                if updates:
                    runtime.vault_update(cfg, host, originals)
                runtime.save_contract(cfg, original_contract)
                raise
    return SetupDeviceCredentialAdmissionResult(
        contract=contract,
        presence=presence,
        ready=ready,
        replay=replay,
    )


@dataclass(frozen=True)
class SetupInitStartResult:
    """Transport-free result of one setup-init start request."""

    job: dict
    replay: bool


@dataclass(frozen=True)
class SetupInitStartRuntime:
    """Dashboard-owned state and effects required to start setup init."""

    setup_lock: Callable[[], Any]
    observe_state: Callable[..., dict | None]
    load_contract: Callable[..., dict]
    snapshot_discovery: Callable[[], dict | None]
    contract_ready: Callable[..., bool]
    validate_request: Callable[..., dict]
    init_lock: Callable[[], Any]
    current_job: Callable[[], dict | None]
    publish_job: Callable[[dict | None], Any]
    new_job_id: Callable[[], str]
    build_command: Callable[..., tuple]
    now: Callable[[], float]
    update_state: Callable[..., Any]
    worker_factory: Callable[..., Any]
    worker_target: Callable[..., Any]
    remove_tree: Callable[..., Any]
    settle_launch: Callable[[], Any]


_SETUP_INIT_NEEDS_SETTLEMENT = object()


def start_setup_init(cfg, body, owner, *, runtime: SetupInitStartRuntime):
    result = _start_setup_init_once(cfg, body, owner, runtime=runtime, allow_settlement=True)
    if result is _SETUP_INIT_NEEDS_SETTLEMENT:
        # The first fully validated pure admission returned both state gates
        # without materializing adapters. Replay never reaches this path.
        runtime.settle_launch()
        return _start_setup_init_once(cfg, body, owner, runtime=runtime, allow_settlement=False)
    return result


def _start_setup_init_once(cfg, body, owner, *, runtime: SetupInitStartRuntime, allow_settlement):
    """Admit, prepare, and launch one owner-bound setup-init request."""
    secret_dir = ""
    job_id = ""
    job = launch = None
    reservation = None
    try:
        with runtime.setup_lock():
            try:
                try:
                    state = runtime.observe_state(cfg)
                    contract = runtime.load_contract(cfg)
                    discovery = runtime.snapshot_discovery() or {}
                    if not state:
                        raise SetupContractError(
                            "setup_expired",
                            "The setup window expired.",
                            status=410,
                        )
                    if state.get("username") != owner:
                        raise SetupContractError(
                            "setup_owner_mismatch",
                            "Setup belongs to another operator.",
                            status=403,
                        )
                    if (
                        not contract
                        or contract.get("setup_id") != state.get("setup_id")
                        or contract.get("contract_id") != state.get("active_contract_id")
                    ):
                        raise SetupContractError(
                            "stale_contract",
                            "A current selection contract is required.",
                            "contract_id",
                            409,
                        )
                    if (
                        discovery.get("state") != "succeeded"
                        or discovery.get("id") != state.get("active_discovery_id")
                        or discovery.get("setup_id") != state.get("setup_id")
                    ):
                        raise SetupContractError(
                            "stale_discovery",
                            "A current successful discovery is required.",
                            "discovery_id",
                            409,
                        )
                    if not runtime.contract_ready(cfg, state["setup_id"], contract):
                        raise SetupContractError(
                            "credentials_incomplete",
                            "Required device credentials are incomplete.",
                            status=422,
                        )
                    request = runtime.validate_request(body, state, contract, discovery)
                    with runtime.init_lock():
                        current = runtime.current_job()
                        existing = snapshot_init_job(current)["job"] if current else None
                        occupied = bool(current and (
                            _setup_worker_launch_unsettled(current)
                            or current.get("state") in {"queued", "running"}))
                    replay = bool(
                        existing
                        and existing.get("setup_id") == state.get("setup_id")
                        and existing.get("client_request_id")
                        == request["client_request_id"]
                    )
                    if replay:
                        return SetupInitStartResult(job=existing, replay=True)
                    if occupied:
                        if allow_settlement:
                            return _SETUP_INIT_NEEDS_SETTLEMENT
                        raise SetupContractError(
                            "init_running",
                            "A setup init job is already running.",
                            status=409,
                        )
                    job_id = runtime.new_job_id()
                    now = runtime.now()
                    job = {
                        "id": job_id,
                        "setup_id": state["setup_id"],
                        "owner": state["username"],
                        "client_request_id": request["client_request_id"],
                        "state": "queued",
                        "pid": None,
                        "started_at": now,
                        "updated_at": now,
                        "finished_at": None,
                        "returncode": None,
                        "initialized": False,
                        "web_setup_complete": False,
                        "progress": {
                            "phase": 0,
                            "phase_name": "Queued",
                            "current": 0,
                            "total": 12,
                            "message": "Initialization queued.",
                        },
                        "lines": ["starting web-launched freq init --headless"],
                    }
                    launch = _SetupInitWorkerLaunch(job, runtime.worker_target, None)
                    reservation = _SetupInitPreparation(
                        launch, cfg, request, contract, discovery)
                    launch.preparation = reservation
                    try:
                        with runtime.init_lock():
                            try:
                                job["_worker_launch"] = launch
                                runtime.publish_job(job)
                            except BaseException as failure:
                                reservation.remember(0, failure)
                    except BaseException as failure:
                        reservation.remember(1, failure)
                    if reservation.failure is not None:
                        raise reservation.failure from None
                    reservation.publication_stage = 'returned'
                    directory = reservation.directory
                    if (type(directory) is not _SetupInitDirectoryDuty
                            or directory.launch is not launch or directory.job is not job
                            or directory.cfg is not cfg or directory.used is not False):
                        raise SetupContractError('init_prepare_failed',
                            'Setup adapter acquisition is unavailable.', status=500)
                    reservation.command_stage = 'pending'
                    try:
                        # Retain the exact returned object before unpacking/args work.
                        reservation.command_result = runtime.build_command(
                            cfg, request, contract, discovery, job_id,
                            _directory_duty=reservation.directory)
                        cmd, env, secret_dir = reservation.command_result
                        reservation.args = (job_id, cmd, env, secret_dir, state["setup_id"])
                        launch.args = reservation.args
                    except BaseException as failure:
                        reservation.remember(2, failure)
                        raise
                    reservation.command_stage = 'returned'
                    runtime.update_state(
                        cfg,
                        phase="initializing",
                        active_init_job_id=job_id,
                        last_error_code=None,
                    )
                except SetupContractError as failure:
                    if reservation is not None:
                        reservation.remember(2, failure)
                    raise
                except Exception as body_failure:
                    if reservation is not None:
                        reservation.remember(2, body_failure)
                    # Root the actual raw preparation failure before any later effect.
                    # Initial construction/publication without a matching root remains
                    # earlier scope; never reconstruct authority from a textual id.
                    root = launch if (type(launch) is _SetupInitWorkerLaunch
                        and launch.job is job and job.get("_worker_launch") is launch) else None
                    may_remove = launch is None
                    if root is not None:
                        root.prep_failures[0] = root.prep_failure = body_failure
                        may_remove = (root.used is False and root.stage == 'prepared'
                                      and root.worker is None and root.child is None)
                        root.used = True
                        root.prep_stage = 'pending'
                    cleanup_failure = report_body_failure = report_gate_failure = None
                    try:
                        if secret_dir and may_remove:
                            if root is not None:
                                root.prep_cleanup_stage = 'pending'
                            runtime.remove_tree(secret_dir, ignore_errors=True)
                            if root is not None:
                                # API return only; ignore_errors is no absence proof.
                                root.prep_cleanup_stage = 'returned'
                    except BaseException as failure:
                        cleanup_failure = failure
                        if root is not None:
                            root.prep_failures[1] = failure
                    if root is not None:
                        root.prep_report_stage = 'pending'
                    try:
                        with runtime.init_lock():
                            try:
                                current = runtime.current_job()
                                if (root is not None and current is job
                                        and current.get("_worker_launch") is root):
                                    job["state"] = "failed"
                                    job["error"] = "setup init could not be prepared"
                            except BaseException as failure:
                                # Capture before the original gate release can fail.
                                # Original gate release is independent of body success; delay
                                # rethrow until both raw outcomes are retained.
                                report_body_failure = failure
                                if root is not None:
                                    root.prep_failures[2] = failure
                    except BaseException as failure:
                        report_gate_failure = failure
                        if root is not None:
                            root.prep_failures[3] = failure
                    else:
                        if root is not None and report_body_failure is None:
                            root.prep_report_stage = 'returned'
                    first = body_failure
                    for later in (cleanup_failure, report_body_failure, report_gate_failure):
                        if later is not None:
                            first = _setup_worker_first(first, later)
                    if root is not None:
                        root.prep_failure = first
                        root.prep_stage = 'failed'
                    if (not issubclass(type(first), Exception)
                            or issubclass(type(first), MemoryError)):
                        raise first from None
                    raise SetupContractError(
                        "init_prepare_failed",
                        "Setup init could not be prepared.",
                        status=500,
                    ) from None
                except BaseException as failure:
                    if reservation is not None:
                        reservation.remember(2, failure)
                    raise
            finally:
                if reservation is not None:
                    # Existing cleanup/report raw outcomes precede setup exit.
                    for failure in launch.prep_failures:
                        if failure is not None:
                            reservation.remember(2, failure)
    except BaseException as failure:
        if reservation is not None:
            reservation.remember(3, failure)
            first = reservation.failure
            if (not issubclass(type(first), Exception)
                    or issubclass(type(first), MemoryError)):
                raise first from None
        raise

    reservation.setup_returned = True

    job["_worker_launch"].launch(cfg, runtime)
    return SetupInitStartResult(job=job, replay=False)


@dataclass(frozen=True)
class SetupDiscoveryAdmission:
    """Atomic admission decision for one setup-discovery candidate."""

    existing: dict | None
    replay: bool
    conflict: bool


@dataclass(frozen=True)
class SetupDiscoveryAdmissionRuntime:
    """Dashboard-owned state required by discovery-job admission."""

    current_lock: Callable[[], Any]
    current_job: Callable[[], dict | None]
    publish_job: Callable[[dict], Any]


def admit_setup_discovery_job(job, *, runtime: SetupDiscoveryAdmissionRuntime):
    """Atomically replay, reject, or publish one discovery candidate."""
    with runtime.current_lock():
        existing = snapshot_discovery_job(runtime.current_job())
        client_request_id = job.get("client_request_id")
        replay = bool(
            existing
            and existing.get("setup_id") == job.get("setup_id")
            and client_request_id
            and existing.get("client_request_id") == client_request_id
        )
        conflict = bool(
            existing
            and existing.get("state") in {"queued", "running"}
            and not replay
        )
        if not replay and not conflict:
            runtime.publish_job(job)
    return SetupDiscoveryAdmission(existing=existing, replay=replay, conflict=conflict)


@dataclass(frozen=True)
class SetupDiscoverySecretRuntime:
    """Dashboard-owned state and vault effects required by secret storage."""

    setup_lock: Callable[[], Any]
    current_lock: Callable[[], Any]
    current_job: Callable[[], dict | None]
    clear_job: Callable[[], Any]
    vault_init: Callable[..., Any]
    vault_set: Callable[..., Any]
    vault_get: Callable[..., Any]


def store_setup_discovery_bootstrap_secret(
    cfg,
    setup_id,
    job_id,
    password,
    *,
    runtime: SetupDiscoverySecretRuntime,
):
    """Store and verify one bootstrap secret or clean its failed admission."""
    setup_vault_host = f"setup:{setup_id}"
    try:
        with runtime.setup_lock():
            if not os.path.exists(cfg.vault_file) and not runtime.vault_init(cfg):
                raise OSError("vault initialization failed")
            if not runtime.vault_set(cfg, setup_vault_host, "bootstrap_password", password):
                raise OSError("vault write failed")
            if runtime.vault_get(cfg, setup_vault_host, "bootstrap_password") != password:
                raise OSError("vault verification failed")
    except Exception:
        with runtime.current_lock():
            job = runtime.current_job()
            if job and job.get("id") == job_id:
                runtime.clear_job()
        return None
    return setup_vault_host


@dataclass(frozen=True)
class SetupDiscoveryStateRuntime:
    """Dashboard-owned state and effects required by state persistence."""

    current_lock: Callable[[], Any]
    current_job: Callable[[], dict | None]
    clear_job: Callable[[], Any]
    vault_delete: Callable[..., Any]
    update_state: Callable[..., Any]


def persist_setup_discovery_state(
    cfg,
    job_id,
    setup_vault_host,
    *,
    runtime: SetupDiscoveryStateRuntime,
):
    """Persist discovery state or clean the matching failed admission."""
    try:
        runtime.update_state(
            cfg,
            phase="discovering",
            active_discovery_id=job_id,
            active_contract_id=None,
            last_error_code=None,
        )
    except (OSError, ValueError):
        runtime.vault_delete(cfg, setup_vault_host, "bootstrap_password")
        with runtime.current_lock():
            job = runtime.current_job()
            if job and job.get("id") == job_id:
                runtime.clear_job()
        return False
    return True


@dataclass(frozen=True)
class SetupDiscoveryLaunchRuntime:
    """Dashboard-owned state and effects required by worker launch."""

    current_lock: Callable[[], Any]
    current_job: Callable[[], dict | None]
    clear_job: Callable[[], Any]
    worker_target: Callable[..., Any]
    thread_factory: Callable[..., Any]
    vault_delete: Callable[..., Any]
    update_state: Callable[..., Any]


def launch_setup_discovery_worker(
    cfg,
    job_id,
    setup_vault_host,
    *,
    runtime: SetupDiscoveryLaunchRuntime,
):
    """Start one discovery worker or roll back its matching admission."""
    with runtime.current_lock():
        job = runtime.current_job()
        if job and job.get("id") == job_id:
            job["state"] = "running"
    worker = runtime.thread_factory(
        target=runtime.worker_target,
        args=(cfg, job_id),
        daemon=True,
        name=f"freq-setup-discovery-{job_id[:12]}",
    )
    try:
        worker.start()
    except Exception:
        runtime.vault_delete(cfg, setup_vault_host, "bootstrap_password")
        with runtime.current_lock():
            job = runtime.current_job()
            if job and job.get("id") == job_id:
                runtime.clear_job()
        try:
            runtime.update_state(
                cfg,
                phase="blocked",
                active_discovery_id=None,
                last_error_code="discovery_start_failed",
            )
        except (OSError, ValueError):
            pass
        return False
    return True


def update_discovery_progress(
    job_id,
    phase,
    current,
    total,
    message,
    *,
    current_lock,
    current_job,
):
    """Update the matching live discovery job while holding its owner lock."""
    with current_lock():
        job = current_job()
        if not job or job.get("id") != job_id:
            return
        job["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        job["progress"] = {
            "phase": phase,
            "current": int(current or 0),
            "total": int(total or 0),
            "message": str(message or "")[:240],
        }


@dataclass(frozen=True)
class SetupDiscoveryWorkerRuntime:
    """Dashboard-owned state and effects required by the discovery worker."""

    current_lock: Callable[[], Any]
    setup_lock: Callable[[], Any]
    current_job: Callable[[], dict | None]
    vault_get: Callable[..., Any]
    run_discovery: Callable[..., dict]
    update_progress: Callable[..., Any]
    load_contract: Callable[..., Any]
    retire_contract: Callable[..., Any]
    update_state: Callable[..., Any]


def run_setup_discovery_job(cfg, job_id, *, runtime: SetupDiscoveryWorkerRuntime):
    """Run one setup discovery job with injected dashboard state ownership."""
    password_file = ""
    known_hosts_file = ""
    try:
        with runtime.current_lock():
            job = runtime.current_job()
            if not job or job.get("id") != job_id:
                return
            setup_id = job["setup_id"]
            cluster = json.loads(json.dumps(job["cluster"]))
            username = job["bootstrap_username"]
        password = runtime.vault_get(cfg, f"setup:{setup_id}", "bootstrap_password")
        if not password:
            raise RuntimeError("bootstrap_secret_missing")
        fd, password_file = tempfile.mkstemp(prefix="freq-setup-discovery-")
        try:
            os.write(fd, password.encode())
        finally:
            os.close(fd)
        os.chmod(password_file, 0o600)
        known_hosts_file = f"{password_file}.known-hosts"
        password = ""

        results = runtime.run_discovery(
            cluster,
            username,
            password_file,
            progress=lambda phase, current, total, message: runtime.update_progress(
                job_id, phase, current, total, message
            ),
        )
        finished = datetime.datetime.now(datetime.timezone.utc).isoformat()
        resource_count = len(results.get("resources") or []) + len(results.get("devices") or [])
        with runtime.current_lock():
            job = runtime.current_job()
            if job and job.get("id") == job_id:
                job.update(
                    {
                        "state": "succeeded",
                        "updated_at": finished,
                        "finished_at": finished,
                        "poll_after_ms": 0,
                        "progress": {
                            "phase": "complete",
                            "current": resource_count,
                            "total": resource_count,
                            "message": (
                                f"Discovered {len(results.get('resources') or [])} virtual resources "
                                f"and {len(results.get('devices') or [])} devices."
                            ),
                        },
                        "results": results,
                    }
                )
        with runtime.setup_lock():
            previous_contract = runtime.load_contract(cfg)
            runtime.retire_contract(cfg, previous_contract)
            runtime.update_state(
                cfg,
                phase="selecting",
                active_discovery_id=job_id,
                active_contract_id=None,
            )
    except Exception as exc:
        code = (
            str(exc)
            if str(exc) in {"pve_bootstrap_failed", "bootstrap_secret_missing"}
            else "discovery_failed"
        )
        finished = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with runtime.current_lock():
            job = runtime.current_job()
            if job and job.get("id") == job_id:
                job.update(
                    {
                        "state": "failed",
                        "updated_at": finished,
                        "finished_at": finished,
                        "poll_after_ms": 0,
                        "error": {
                            "code": code,
                            "message": "Discovery could not complete from the declared PVE bootstrap targets.",
                            "retryable": True,
                        },
                    }
                )
        try:
            runtime.update_state(cfg, phase="blocked", last_error_code=code)
        except (OSError, ValueError):
            pass
    finally:
        for path in (password_file, known_hosts_file):
            if path:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass


SETUP_INIT_CANCEL_REQUESTED = "requested"
SETUP_INIT_CANCEL_NOT_FOUND = "not_found"
SETUP_INIT_CANCEL_NOT_RUNNING = "not_running"


@dataclass(frozen=True)
class SetupInitCancelAdmissionRuntime:
    """Injected cancellation controller used by HTTP admission."""

    request_cancel: Callable[[str, str], str]


@dataclass(frozen=True)
class SetupInitCancelResult:
    """Typed accepted cancellation projection."""

    job_id: str
    state: str
    poll_after_ms: int


def cancel_setup_init(
    body,
    owner,
    *,
    runtime: SetupInitCancelAdmissionRuntime,
):
    """Validate and interpret one owner-bound setup-init cancellation request."""
    if not isinstance(body, dict):
        raise SetupContractError("invalid_json", "Invalid setup init cancellation request.")
    extra_fields = sorted(str(key) for key in body if key != "id")
    if extra_fields:
        raise SetupContractError(
            "unknown_field",
            "Setup init cancellation accepts only the init job id.",
            field=extra_fields[0],
        )
    raw_job_id = body.get("id")
    if raw_job_id is None or raw_job_id == "":
        raise SetupContractError("required_field", "Init job id is required.", field="id")
    if not isinstance(raw_job_id, str) or re.fullmatch(r"[0-9a-f]{32}", raw_job_id) is None:
        raise SetupContractError(
            "init_not_found",
            "Init job was not found.",
            field="id",
            status=404,
        )

    outcome = runtime.request_cancel(raw_job_id, owner)
    if outcome == SETUP_INIT_CANCEL_NOT_FOUND:
        raise SetupContractError("init_not_found", "Init job was not found.", status=404)
    if outcome == SETUP_INIT_CANCEL_NOT_RUNNING:
        raise SetupContractError("init_not_running", "Init job is not running.", status=409)
    if outcome != SETUP_INIT_CANCEL_REQUESTED:
        raise SetupContractError(
            "init_cancel_failed",
            "Init cancellation returned an invalid outcome.",
            status=500,
        )
    return SetupInitCancelResult(
        job_id=raw_job_id,
        state=SETUP_INIT_CANCEL_REQUESTED,
        poll_after_ms=250,
    )


@dataclass(frozen=True)
class SetupInitCancellationRuntime:
    """Dashboard-owned state required by the setup cancellation controller."""

    current_lock: Callable[[], Any]
    current_job: Callable[[], dict | None]


def deliver_setup_init_cancel(job_id, process, *, runtime: SetupInitCancellationRuntime):
    """Consume one original signal attempt; API return is never child delivery."""
    duty = None
    claimed = replay = False
    try:
        with runtime.current_lock():
            job = runtime.current_job()
            if not job or job.get('id') != job_id:
                raise SetupContractError('init_cancel_delivery_unknown',
                    'Init cancellation outcome is unknown.', status=503)
            duty = _setup_cancel_duty(job)
            if (duty.admission_returned is not True or duty.used
                    or duty.failure is not None
                    or job.get('state') not in {'queued', 'running'}):
                replay = True
            else:
                _setup_cancel_process(duty, process)
                duty.used = True
                duty.stage = 'pending'
                job['cancel_signal_sent'] = True
                job['cancel_delivery_failed'] = False
                claimed = True
    except BaseException as failure:
        if type(duty) is not _SetupInitCancelDuty:
            raise
        duty.remember(failure)

    if replay:
        # A concurrent request's unavailable result is not a new signal failure
        # and cannot poison the original in-flight operation's raw journal.
        if duty.stage == 'returned' and duty.failure is None:
            return
        duty.refuse_unknown()
    if claimed and duty.failure is None:
        try:
            process.send_signal(signal.SIGINT)
        except BaseException as failure:
            duty.remember(failure)
        else:
            duty.native_returned = True
    if duty.report_stage == 'unused':
        duty.report_stage = 'pending'
        try:
            with runtime.current_lock():
                job = runtime.current_job()
                if (_setup_cancel_launch(job) is not duty.launch or job is not duty.job
                        or duty.launch.cancellation is not duty):
                    raise SetupContractError('init_cancel_delivery_unknown',
                        'Init cancellation outcome is unknown.', status=503)
                job['cancel_requested'] = True
                job['cancel_signal_sent'] = True
                job['cancel_delivery_failed'] = False
        except BaseException as failure:
            duty.remember(failure)
        else:
            duty.report_stage = 'returned'
    if duty.native_returned and duty.report_stage == 'returned' and duty.failure is None:
        duty.stage = 'returned'
        return
    duty.refuse_unknown()


def publish_setup_init_process(job_id, process, *, runtime: SetupInitCancellationRuntime):
    """Publish only the actual original child process, independent of signal outcome."""
    duty = None
    deliver = False
    try:
        with runtime.current_lock():
            job = runtime.current_job()
            launch = _setup_cancel_launch(job)
            if launch is None or launch.args[0] is not job_id:
                return False
            child = launch.child
            if (type(child) is not _SetupInitChildDuty or child.launch is not launch
                    or child.job is not job or child.process is not process
                    or child.process_stage != 'returned'):
                return False
            if job.get('process') is not None and job.get('process') is not process:
                return False
            if child.cancel_publish_stage != 'unused':
                return (child.cancel_publish_stage == 'returned'
                        and child.cancel_process_ready is True
                        and job.get('process') is process)
            child.cancel_publish_stage = 'pending'
            job['process'] = process
            job['pid'] = process.pid
            if job.get('cancel_requested') is True or launch.cancellation is not None:
                duty = _setup_cancel_duty(job)
                # Even if intent admission has not returned yet, attempt the
                # later live guard outside this gate. Together with request's
                # fresh process recheck, neither publication/intent order loses
                # a queued request. The guard never consumes pending admission.
                deliver = True
    except BaseException as failure:
        if type(duty) is _SetupInitCancelDuty:
            duty.remember(failure)
            duty.refuse_unknown()
        raise
    # This one-way primitive records only this exact publisher's known
    # state-gate return. A lost return never permits another handle/publication.
    child.cancel_publish_stage = 'returned'
    child.cancel_process_ready = True
    if deliver:
        try:
            deliver_setup_init_cancel(job_id, process, runtime=runtime)
        except SetupContractError as failure:
            if failure.code != 'init_cancel_delivery_unknown':
                raise
            # The exact process publication returned. Cancellation uncertainty
            # remains rooted separately and prevents launch settlement; normal
            # worker output/wait need not be abandoned for an ordinary signal
            # outcome. Protected signal/report failures still escape raw.
    return True


def request_setup_init_cancel(job_id, owner, *, runtime: SetupInitCancellationRuntime):
    """Record one intent, acknowledge its state return, then recheck the child."""
    duty = None
    process = None
    created_here = False
    unknown = False
    try:
        with runtime.current_lock():
            job = runtime.current_job()
            if (not isinstance(job_id, str) or not isinstance(owner, str)
                    or not job or job.get('id') != job_id or job.get('owner') != owner):
                return SETUP_INIT_CANCEL_NOT_FOUND
            if job.get('state') not in {'queued', 'running'}:
                return SETUP_INIT_CANCEL_NOT_RUNNING
            launch = _setup_cancel_launch(job)
            created_here = (launch is not None and launch.cancellation is None
                            and job.get('cancel_requested') is not True)
            duty = _setup_cancel_duty(job, create=True)
        if created_here:
            # Never change a stage or clear a failure here. This independent
            # one-way bit is only the known return of original intent admission;
            # a lost constructor/caller/gate return leaves it false forever.
            duty.admission_returned = True
        with runtime.current_lock():
            current = runtime.current_job()
            if (current is not duty.job or _setup_cancel_launch(current) is not duty.launch
                    or duty.launch.cancellation is not duty):
                raise SetupContractError('init_cancel_delivery_unknown',
                    'Init cancellation outcome is unknown.', status=503)
            if (duty.admission_returned is not True or duty.failure is not None or duty.used
                    or current.get('state') not in {'queued', 'running'}):
                unknown = duty.stage != 'returned' or duty.failure is not None
            else:
                candidate = current.get('process')
                child = duty.launch.child
                if (candidate is not None and type(child) is _SetupInitChildDuty
                        and child.cancel_process_ready is True):
                    _setup_cancel_process(duty, candidate)
                    process = candidate
    except BaseException as failure:
        if type(duty) is _SetupInitCancelDuty:
            duty.remember(failure)
            duty.refuse_unknown()
        raise
    if unknown:
        duty.refuse_unknown()
    if process is not None:
        deliver_setup_init_cancel(job_id, process, runtime=runtime)
    return SETUP_INIT_CANCEL_REQUESTED


@dataclass(frozen=True)
class SetupInitWorkerRuntime:
    """Dashboard-owned state and side effects required by the setup worker."""

    init_lock: Any
    setup_lock: Any
    current_job: Callable[[], dict | None]
    popen: Callable[..., Any]
    publish_process: Callable[[str, Any], bool]
    load_config: Callable[..., Any]
    write_web_setup_markers: Callable[[Any], None]
    delete_setup_vault_namespace: Callable[[Any, str], None]
    clear_setup_contract: Callable[[Any], None]
    clear_setup_state: Callable[[Any], None]
    update_setup_state: Callable[..., None]
    schedule_runtime_handoff: Callable[[Any], bool]
    redact_line: Callable[[str, str], str]
    parse_progress: Callable[[str], dict | None]
    now: Callable[[], float]
    remove_tree: Callable[[str], None]


def run_setup_init_job(
    job_id,
    cmd,
    env,
    secret_dir,
    setup_id="",
    *,
    runtime: SetupInitWorkerRuntime,
):
    """Fence this invoking parent before entering the original child worker."""
    retirement_failure = None
    try:
        from freq.core.read_source_epoch import retire_process_reads
        retire_process_reads()
    except BaseException as failure:
        retirement_failure = failure
    if retirement_failure is None:
        return _run_setup_init_job_after_read_retirement(
            job_id, cmd, env, secret_dir, setup_id, runtime=runtime
        )

    # The child was never entered. Failure reporting and disposal are independent;
    # neither may swallow the original Control/Memory or acknowledge child exit.
    reporting_failure = cleanup_failure = None
    try:
        with runtime.init_lock:
            job = runtime.current_job()
            if job and job.get("id") == job_id:
                job["state"] = "failed"
                job["error"] = "setup init source retirement failed before child launch"
                job["process"] = None
                job["finished_at"] = runtime.now()
                job["updated_at"] = runtime.now()
    except BaseException as failure:
        reporting_failure = failure
    try:
        if secret_dir:
            runtime.remove_tree(secret_dir)
    except FileNotFoundError:
        pass
    except BaseException as failure:
        cleanup_failure = failure
    first = retirement_failure
    for later in (reporting_failure, cleanup_failure):
        if later is not None and (
            issubclass(type(first), Exception) and (
                not issubclass(type(later), Exception)
                or not issubclass(type(first), MemoryError)
                and issubclass(type(later), MemoryError)
            )
        ):
            first = later
    raise first from None


def _run_setup_init_job_after_read_retirement(
    job_id,
    cmd,
    env,
    secret_dir,
    setup_id="",
    *,
    runtime: SetupInitWorkerRuntime,
):
    """Run one setup child while the dashboard retains job and lock ownership."""
    duty = _bind_setup_init_child(job_id, cmd, env, secret_dir, setup_id, runtime)
    handoff_cfg = None
    succeeded = False
    terminal_report_returned = False
    try:
        with runtime.init_lock:
            job = runtime.current_job()
            if job is duty.job and job.get("_worker_launch") is duty.launch:
                job["state"] = "running"
                job["progress"] = {
                    "phase": 0,
                    "phase_name": "Starting",
                    "current": 0,
                    "total": 12,
                    "message": "Starting headless initialization.",
                }
        duty.spawn(runtime)
        duty.read_stage = "pending"
        while duty.stream is not None:
            line = duty.next_output_line()
            if line is None:
                break
            with runtime.init_lock:
                job = runtime.current_job()
                if job is duty.job and job.get("_worker_launch") is duty.launch:
                    safe_line = runtime.redact_line(line, secret_dir)
                    job.setdefault("lines", []).append(safe_line)
                    progress = runtime.parse_progress(safe_line)
                    if progress:
                        job["progress"] = progress
                    job["updated_at"] = runtime.now()
                    job["lines"] = job["lines"][-1000:]
        duty.read_stage = "returned"
        rc = duty.wait()
        duty.close_output()
        cfg = runtime.load_config(force=True)
        handoff_cfg = cfg
        initialized = os.path.isfile(os.path.join(cfg.conf_dir, ".initialized"))
        marker_error = None
        if rc == 0 and initialized:
            try:
                runtime.write_web_setup_markers(cfg)
            except OSError as failure:
                duty.remember(failure)
                marker_error = "setup markers could not be written"
        web_complete = os.path.isfile(os.path.join(cfg.conf_dir, ".web-setup-complete"))
        cleanup_error = None
        try:
            if not duty.cleanup_adapters(runtime):
                raise OSError("transient init adapter cleanup remains unresolved")
        except BaseException as failure:
            duty.remember(failure)
            cleanup_error = "transient init adapters could not be removed"
        succeeded = rc == 0 and initialized and web_complete and not marker_error and not cleanup_error
        if not succeeded and web_complete:
            try:
                os.unlink(os.path.join(cfg.conf_dir, ".web-setup-complete"))
                web_complete = False
            except OSError as failure:
                duty.remember(failure)
                marker_error = marker_error or "failed setup marker could not be removed"
        if succeeded and setup_id:
            try:
                with runtime.setup_lock:
                    runtime.delete_setup_vault_namespace(cfg, setup_id)
                    runtime.clear_setup_contract(cfg)
                    runtime.clear_setup_state(cfg)
            except BaseException as failure:
                duty.remember(failure)
                cleanup_error = "setup secrets could not be removed"
                succeeded = False
        if not succeeded and web_complete:
            try:
                os.unlink(os.path.join(cfg.conf_dir, ".web-setup-complete"))
                web_complete = False
            except OSError as failure:
                duty.remember(failure)
                marker_error = marker_error or "failed setup marker could not be removed"
        with runtime.init_lock:
            job = runtime.current_job()
            if job is duty.job and job.get("_worker_launch") is duty.launch:
                job["state"] = "succeeded" if succeeded else "failed"
                job["returncode"] = rc
                job["initialized"] = initialized
                job["web_setup_complete"] = web_complete
                # Exact process remains retained; terminal DATA is not closure.
                if marker_error or cleanup_error:
                    job["error"] = marker_error or cleanup_error
                elif not succeeded:
                    job["error"] = "freq init did not complete successfully"
                else:
                    job["progress"] = {
                        "phase": 12,
                        "phase_name": "Verification",
                        "current": 12,
                        "total": 12,
                        "message": "Initialization and browser setup completed.",
                    }
                job["finished_at"] = runtime.now()
                job["updated_at"] = runtime.now()
        terminal_report_returned = True
        if not succeeded:
            try:
                runtime.update_setup_state(cfg, phase="blocked", last_error_code="init_failed")
            except (OSError, ValueError) as failure:
                duty.remember(failure)
    except BaseException as failure:
        duty.remember(failure)
        try:
            with runtime.init_lock:
                job = runtime.current_job()
                if job is duty.job and job.get("_worker_launch") is duty.launch:
                    job["state"] = "failed"
                    job["error"] = "setup init worker failed"
                    job["finished_at"] = runtime.now()
                    job["updated_at"] = runtime.now()
        except BaseException as failure:
            duty.remember(failure)
        try:
            runtime.update_setup_state(
                runtime.load_config(force=True),
                phase="blocked",
                last_error_code="init_failed",
            )
        except BaseException as failure:
            duty.remember(failure)
    finally:
        # Known stream closure is independent of body/report failure. Never
        # introduce a wait here or retry a pending close/removal operation.
        try:
            duty.close_output()
        except BaseException as failure:
            duty.remember(failure)
        try:
            duty.cleanup_adapters(runtime)
        except BaseException as failure:
            duty.remember(failure)
        if (succeeded and duty.failure_count == 0
                and env.get("FREQ_WEB_INIT") == "1" and handoff_cfg is not None):
            try:
                if runtime.schedule_runtime_handoff(handoff_cfg):
                    with runtime.init_lock:
                        job = runtime.current_job()
                        if job is duty.job and job.get("_worker_launch") is duty.launch:
                            job.setdefault("lines", []).append(
                                "scheduled dashboard handoff to freq-serve.service"
                            )
                            job["updated_at"] = runtime.now()
            except BaseException as failure:
                duty.remember(failure)
        if succeeded and terminal_report_returned and duty.failure_count:
            # C01: later handoff/report failures cannot leave the earlier
            # succeeded label as a delivery claim. This distinct late report
            # is attempted once and cannot hide the first retained failure.
            try:
                with runtime.init_lock:
                    job = runtime.current_job()
                    if job is duty.job and job.get("_worker_launch") is duty.launch:
                        job["state"] = "failed"
                        job["error"] = "setup runtime handoff did not complete"
                        job["updated_at"] = runtime.now()
            except BaseException as failure:
                duty.remember(failure)
        first = duty.selected_failure()
        if first is not None and (
                not issubclass(type(first), Exception)
                or issubclass(type(first), MemoryError)):
            raise first from None
        # A first ordinary failure can retain unknown work too. Only an
        # entirely known returning body is eligible for later thread observation.
        if duty.failure_count == 0:
            duty.completion_stage = 'returned'
