"""Fixed native per-node credential acquisition; never installation authority.

For the future original owned startup worker only. The original process owner
must exist before the first syscall and retain physical retirement on lost
returns/uncertain close. Synchronous syscalls supply no hard wall-time guarantee.
Expected UID and endpoint are retained native-owner data, not caller grants.
No request-selected path, shared token, SSH or password fallback exists here.
The returned secret stays private to the genuine owner; never log or serialize
it. Python immutable bytes are not claimed to be securely zeroized.
"""
import hashlib
import ipaddress
import math
import os
import stat
import threading
import time


class PilotCredentialUnavailable(Exception):
    def __init__(self):
        super().__init__('Pilot credential unavailable')


class PilotCredentialClosureUncertain(Exception):
    pass


def _identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid,
            value.st_gid, value.st_nlink, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


class FixedNodeTokenReader:
    """One acquisition/read and once-only reverse close; data, not a grant.

    No successful return may install a service or authenticate a request.
    Native installation/source/credential cohort and writer exclusion remain
    the original parent's responsibility, including before/after this leaf.
    """
    __slots__ = ('_uid', '_parts', '_fds', '_states', '_ids', '_opened',
                 '_read', '_closed', '_thread', '_end', '_token_name', '_acquired',
                 '_close_errors', '_close_failure')

    def __init__(self, expected_uid, retained_endpoint, original_deadline):
        if type(expected_uid) is not int or not 0 <= expected_uid <= 4294967294:
            raise PilotCredentialUnavailable()
        if (type(retained_endpoint) is not str or not 0 < len(retained_endpoint) <= 64
                or not retained_endpoint.isascii() or '%' in retained_endpoint):
            raise PilotCredentialUnavailable()
        try:
            ipaddress.ip_address(retained_endpoint)
        except ValueError:
            raise PilotCredentialUnavailable() from None
        if type(original_deadline) is not float or not math.isfinite(original_deadline):
            raise PilotCredentialUnavailable()
        # Match the original per-node store spelling; do not normalize the
        # retained configured literal into a different token-file identity.
        suffix = hashlib.sha256(retained_endpoint.encode('ascii')).hexdigest()[:12]
        self._uid = expected_uid
        self._parts = ('etc', 'freq', 'credentials', 'pve-token-rw-' + suffix)
        # Original pve_transport._pve_api_credentials uses configured principal
        # plus THIS node-scoped name, not the configured shared token's name.
        self._token_name = 'freq-rw-' + suffix
        self._thread = threading.current_thread()
        self._end = original_deadline
        self._fds = [None] * 5
        self._states = ['unused'] * 5
        self._ids = [None] * 5
        self._opened = self._read = self._closed = False
        self._acquired = False
        # Fixed private error slots exist before any descriptor acquisition.
        self._close_errors = [None] * 5
        self._close_failure = None

    def _owner(self):
        if threading.current_thread() is not self._thread:
            raise PilotCredentialUnavailable()

    def _current(self):
        if not time.monotonic() < self._end:
            raise PilotCredentialUnavailable()

    @property
    def node_token_name(self):
        # Nonsecret scalar correspondence only; never a token/currentness grant.
        self._owner()
        return self._token_name

    def _check(self, info, index):
        directory = index < 4
        expected = 0 if index < 3 else self._uid
        if index == 3:
            # The private store itself may be retained under root custody.
            if info.st_uid not in (0, self._uid):
                raise PilotCredentialUnavailable()
        elif info.st_uid != expected:
            raise PilotCredentialUnavailable()
        if directory:
            if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
                raise PilotCredentialUnavailable()
        elif (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
              or info.st_nlink != 1 or info.st_size not in (36, 37)):
            raise PilotCredentialUnavailable()

    def _retain(self, index, descriptor):
        # Record the actual result before later fallible stat/validation.
        self._fds[index] = descriptor
        self._states[index] = 'owned'
        self._current()
        info = os.fstat(descriptor)
        self._check(info, index)
        self._ids[index] = _identity(info)
        self._current()

    def _open(self, index, flags):
        self._current()
        self._states[index] = 'acquire-pending'
        if index == 0:
            descriptor = os.open('/', flags)
        else:
            descriptor = os.open(self._parts[index - 1], flags,
                                 dir_fd=self._fds[index - 1])
        self._retain(index, descriptor)

    def open_fixed(self):
        self._owner()
        if self._opened or self._read or self._closed:
            raise PilotCredentialUnavailable()
        self._opened = True
        dirs = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            self._open(0, dirs)
            for index in range(1, 5):
                flags = dirs if index < 4 else (
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
                self._open(index, flags)
            self._recheck()
            self._acquired = True
        except OSError:
            raise PilotCredentialUnavailable() from None

    def _recheck(self):
        self._current()
        if self._states != ['owned'] * 5:
            raise PilotCredentialUnavailable()
        for index, descriptor in enumerate(self._fds):
            self._current()
            current = os.fstat(descriptor)
            self._check(current, index)
            if _identity(current) != self._ids[index]:
                raise PilotCredentialUnavailable()
            if index:
                self._current()
                named = os.stat(self._parts[index - 1], dir_fd=self._fds[index - 1],
                                follow_symlinks=False)
                self._check(named, index)
                if _identity(named) != self._ids[index]:
                    raise PilotCredentialUnavailable()
            self._current()

    def _bytes(self):
        self._current()
        os.lseek(self._fds[4], 0, os.SEEK_SET)
        self._current()
        raw = bytearray()
        # Capacity38 includes one overflow byte past UUID plus optional LF.
        while len(raw) < 38:
            self._current()
            piece = os.read(self._fds[4], 38 - len(raw))
            self._current()
            if not piece:
                break
            raw.extend(piece)
        if len(raw) != self._ids[4][6] or len(raw) not in (36, 37):
            raise PilotCredentialUnavailable()
        return bytes(raw)

    def read_private_secret(self):
        self._owner()
        if self._closed or not self._acquired or self._read:
            raise PilotCredentialUnavailable()
        self._read = True
        try:
            self._recheck()
            raw = self._bytes()
            self._recheck()
            second = self._bytes()
            self._recheck()
            if raw != second:
                raise PilotCredentialUnavailable()
            if len(raw) == 37:
                if raw[-1] != 10:
                    raise PilotCredentialUnavailable()
                raw = raw[:-1]
            for i, value in enumerate(raw):
                if (value != 45 if i in (8, 13, 18, 23) else value not in b'0123456789abcdef'):
                    raise PilotCredentialUnavailable()
            # Private data return only; no hash/flag/owner or public response.
            self._current()
            return raw
        except OSError:
            raise PilotCredentialUnavailable() from None

    def close(self):
        self._owner()
        self._closed = True
        for index in range(4, -1, -1):
            if self._states[index] != 'owned':
                continue
            self._states[index] = 'close-attempted'
            try:
                os.close(self._fds[index])
            except BaseException as error:
                self._states[index] = 'uncertain'
                # Keep every actual caught failure privately at its fixed FD
                # index; never clear or retry an uncertain descriptor number.
                self._close_errors[index] = error
                first = self._close_failure
                if (first is None or isinstance(first, Exception) and (
                        not isinstance(error, Exception)
                        or not isinstance(first, MemoryError)
                        and isinstance(error, MemoryError))):
                    self._close_failure = error
            else:
                self._states[index] = 'closed'
        # Only after visiting all known owned FDs: first genuine control,
        # then first allocation failure. Repeated close preserves this same
        # failure and the once-only states without another syscall attempt.
        first = self._close_failure
        if first is not None and (
                not isinstance(first, Exception) or isinstance(first, MemoryError)):
            raise first
        if any(state not in ('unused', 'closed') for state in self._states):
            raise PilotCredentialClosureUncertain()

    def close_observations(self):
        self._owner()
        return tuple(self._states)
