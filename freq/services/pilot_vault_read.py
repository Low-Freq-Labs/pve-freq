"""Bounded ORIGINAL OpenSSL Vault read transport, UNREVIEWED/UNEXECUTED.

Same existing AES-256-CBC/PBKDF2 decrypt and machine-id key derivation; no new
Vault format/engine, persistence, init, repair, mutation, DEFAULT selection or
password migration. Only private bounded bytes return, never a user/lease grant.

The original external native process owner must exist BEFORE the first syscall
and retain physical retirement for blocked/lost acquisition/close/Popen returns.
This helper is NOT that owner and cannot recover an object never returned. No
credential access or execution is selected by publishing this source. Native
process/FD/selector/SSL environment qualification is still absent.
"""
import hashlib
import math
import os
import selectors
import signal
import subprocess
import time


_CIPHERTEXT_LIMIT = 1048576
_PLAINTEXT_LIMIT = 1048576
_ERROR_LIMIT = 4096
_CHUNK = 16384
_CLEANUP_ALLOWANCE = 0.5


class _VaultReadUnavailable(Exception):
    def __init__(self):
        super().__init__('Pilot authentication read unavailable')


class OriginalVaultDecrypt:
    """Single native invocation object retained by the original parent first.

    Failed/unknown attempts are spent. Pending native duties remain here for
    parent physical retirement, not retried numeric descriptors or a new job.
    All secret values stay private; Python memory/exception erasure is unproved.
    """
    __slots__ = ('_spent', '_process', '_process_state', '_selector',
                 '_selector_state', '_key_fds', '_key_states', '_streams',
                 '_stream_states', '_first_control', '_failed', '_end',
                 '_pidfd', '_pidfd_state', '_kill_state', '_wait_state')

    def __init__(self):
        # Preallocate all native result slots before the first syscall.
        self._spent = False
        self._process = None
        self._process_state = 'unused'
        self._selector = None
        self._selector_state = 'unused'
        self._key_fds = [None, None]
        self._key_states = ['unused', 'unused']
        self._streams = [None, None, None]
        self._stream_states = ['unused', 'unused', 'unused']
        self._first_control = None
        self._failed = False
        self._end = None
        self._pidfd = None
        self._pidfd_state = 'unused'
        self._kill_state = self._wait_state = 'unused'

    def _failure(self, error):
        self._failed = True
        if not isinstance(error, Exception) and self._first_control is None:
            self._first_control = error

    def _remaining(self, cleanup=False):
        left = self._end - time.monotonic() - (0 if cleanup else _CLEANUP_ALLOWANCE)
        if not math.isfinite(left) or left <= 0:
            raise _VaultReadUnavailable()
        return left

    def _close_key(self, index):
        if self._key_states[index] != 'owned':
            return
        self._key_states[index] = 'close-attempted'
        try:
            os.close(self._key_fds[index])
        except BaseException as error:
            self._key_states[index] = 'uncertain'
            self._failure(error)
        else:
            self._key_states[index] = 'closed'

    def _close_stream(self, index):
        if self._stream_states[index] != 'owned':
            return
        self._stream_states[index] = 'close-attempted'
        try:
            self._streams[index].close()
        except BaseException as error:
            self._stream_states[index] = 'uncertain'
            self._failure(error)
        else:
            self._stream_states[index] = 'closed'

    def _settle(self):
        # Independent cleanup continues after every ordinary/control failure.
        for index in (1, 0):
            self._close_key(index)
        if self._selector_state == 'owned':
            self._selector_state = 'close-attempted'
            try:
                self._selector.close()
            except BaseException as error:
                self._selector_state = 'uncertain'
                self._failure(error)
            else:
                self._selector_state = 'closed'
        # Release every original pipe before waiting for child retirement.
        # In particular, unknown pidfd acquisition must not leave its stdin
        # open while a safe bounded reap waits for that child's EOF.
        for index in (2, 1, 0):
            self._close_stream(index)
        process = self._process
        if process is not None and self._process_state != 'reaped':
            # No status query is needed before original-task termination. A
            # failed query must not skip other independent cleanup. Signal
            # ONLY the retained original pidfd, never a numeric/reused PID.
            if self._pidfd_state == 'owned':
                self._kill_state = 'attempted'
                try:
                    signal.pidfd_send_signal(self._pidfd, signal.SIGKILL, None, 0)
                except ProcessLookupError:
                    # Original task already exited; this is NOT reap proof.
                    self._kill_state = 'original-task-exited'
                except BaseException as error:
                    self._kill_state = 'uncertain'
                    self._failure(error)
                else:
                    self._kill_state = 'signalled'
            else:
                self._kill_state = 'unavailable-original-handle'
                self._failure(_VaultReadUnavailable())
            # Independent original-child reaping still runs after failed kill
            # or failed/expired clock. Zero timeout adds NO positive budget.
            remaining = 0
            try:
                remaining = self._remaining(cleanup=True)
            except BaseException as error:
                self._failure(error)
            self._wait_state = 'attempted'
            try:
                process.wait(timeout=remaining)
                self._process_state = 'reaped'
                self._wait_state = 'reaped'
            except BaseException as error:
                self._process_state = 'uncertain'
                self._wait_state = 'uncertain'
                self._failure(error)
        if self._pidfd_state == 'owned':
            self._pidfd_state = 'close-attempted'
            try:
                os.close(self._pidfd)
            except BaseException as error:
                self._pidfd_state = 'uncertain'
                self._failure(error)
            else:
                self._pidfd_state = 'closed'

    def run(self, ciphertext, machine_id_raw, *, original_deadline):
        """Decrypt once within the supplied ORIGINAL owner's shortened budget.

        Keyword shape validates data only; actual capture provenance must come
        from the original parent/request. No fresh timeout, retry or reacquire.
        Runtime output/counters are bounded before extension. No stderr/native
        exception or secret input is exported in a refusal or diagnostic.
        """
        if self._spent:
            return None
        self._spent = True
        result = None
        try:
            now = time.monotonic()
            if (type(original_deadline) is not float or
                    not math.isfinite(original_deadline) or
                    not now + _CLEANUP_ALLOWANCE < original_deadline <= now + 10.0):
                raise _VaultReadUnavailable()
            self._end = original_deadline
            if (type(ciphertext) is not bytes or
                    not 1 <= len(ciphertext) <= _CIPHERTEXT_LIMIT or
                    type(machine_id_raw) is not bytes or
                    not 1 <= len(machine_id_raw) <= 256):
                raise _VaultReadUnavailable()
            # Original _vault_key strips text then SHA256 UTF8. Require native
            # standard machine-id spelling, with one optional final LF.
            machine_id = machine_id_raw[:-1] if machine_id_raw.endswith(b'\n') else machine_id_raw
            if (len(machine_id) != 32 or
                    any(c not in b'0123456789abcdef' for c in machine_id)):
                raise _VaultReadUnavailable()
            key = hashlib.sha256(machine_id).hexdigest().encode('ascii') + b'\n'
            self._remaining()
            self._key_states[:] = ('acquire-pending', 'acquire-pending')
            read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
            self._key_fds[:] = (read_fd, write_fd)
            self._key_states[:] = ('owned', 'owned')
            # Empty original pipe,65bytes<PIPE_BUF; physical native bound still
            # belongs to the original external owner, not this source check.
            if os.write(write_fd, key) != len(key):
                raise _VaultReadUnavailable()
            self._close_key(1)
            if self._failed:
                raise _VaultReadUnavailable()
            self._remaining()
            self._process_state = 'acquire-pending'
            self._process = subprocess.Popen(
                ['/usr/bin/openssl', 'enc', '-aes-256-cbc', '-d', '-salt',
                 '-pbkdf2', '-pass', 'fd:' + str(read_fd)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=0, close_fds=True, pass_fds=(read_fd,), start_new_session=True,
                env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C',
                     'OPENSSL_CONF': '/dev/null'})
            self._process_state = 'owned'
            self._streams[:] = (self._process.stdin, self._process.stdout, self._process.stderr)
            self._stream_states[:] = ('owned', 'owned', 'owned')
            # Actual isolated original parent MUST enforce before Popen:
            # SIGCHLD not ignored, no SA_NOCLDWAIT, no competing reaper/thread
            # or arbitrary child factory. A shape check/flag is not that proof.
            # Under those qualified conditions an exited unreaped child still
            # has its original PID until this immediate pidfd acquisition.
            self._pidfd_state = 'acquire-pending'
            self._pidfd = os.pidfd_open(self._process.pid, 0)
            self._pidfd_state = 'owned'
            self._close_key(0)
            if self._failed:
                raise _VaultReadUnavailable()
            self._remaining()
            self._selector_state = 'acquire-pending'
            self._selector = selectors.DefaultSelector()
            self._selector_state = 'owned'
            for index, stream in enumerate(self._streams):
                os.set_blocking(stream.fileno(), False)
                self._selector.register(stream, selectors.EVENT_WRITE if index == 0
                                        else selectors.EVENT_READ, index)
            offset = 0
            plaintext = bytearray()
            stderr_count = 0
            while self._selector.get_map():
                events = self._selector.select(self._remaining())
                self._remaining()
                for registered, _ in events:
                    index = registered.data
                    stream = self._streams[index]
                    self._remaining()
                    if index == 0:
                        try:
                            written = os.write(stream.fileno(), memoryview(ciphertext)[offset:offset + _CHUNK])
                        except BlockingIOError:
                            continue
                        if written <= 0:
                            raise _VaultReadUnavailable()
                        offset += written
                        if offset == len(ciphertext):
                            self._selector.unregister(stream)
                            self._close_stream(0)
                            if self._failed:
                                raise _VaultReadUnavailable()
                    else:
                        remaining = (_PLAINTEXT_LIMIT - len(plaintext) if index == 1
                                     else _ERROR_LIMIT - stderr_count)
                        try:
                            # One sentinel byte detects overflow without an
                            # unbounded read or extension of retained output.
                            chunk = os.read(stream.fileno(), min(_CHUNK, remaining + 1))
                        except BlockingIOError:
                            continue
                        if not chunk:
                            self._selector.unregister(stream)
                            continue
                        if len(chunk) > remaining:
                            raise _VaultReadUnavailable()
                        if index == 1:
                            plaintext.extend(chunk)
                        else:
                            stderr_count += len(chunk)  # Discard diagnostics.
                self._remaining()
            # Polling/IO completes before reserved cleanup interval. Original
            # child must exit0 and all original ciphertext must have been sent.
            if offset != len(ciphertext) or self._process.wait(timeout=self._remaining()) != 0:
                raise _VaultReadUnavailable()
            self._process_state = 'reaped'
            self._wait_state = 'reaped'
            result = bytes(plaintext)
            self._remaining()
        except BaseException as error:
            self._failure(error)
        finally:
            self._settle()
            try:
                if self._end is not None:
                    self._remaining(cleanup=True)
            except BaseException as error:
                self._failure(error)
        if self._first_control is not None:
            raise self._first_control
        if self._failed:
            return None
        return result

    def cleanup_observations(self):
        """Private original-parent observations, never native closure proof."""
        return (self._process_state, self._selector_state,
                tuple(self._key_states), tuple(self._stream_states),
                self._pidfd_state, self._kill_state, self._wait_state)


# No CLI, worker launch, credential path, native owner issuer or live effect.
