"""Fixed existing system CA acquisition, uninstalled native source.

Only the original startup owner may use this leaf after retaining its actual
process, principal, immutable code and source/trust writer fence. Root-owned
metadata, equal reads, endpoint strings and returned SSLContext are data and
refusal filters, never that authority. No host trust or credential is changed.
The outer owner retains lost/uncertain native operations and physical cleanup.
"""
import ipaddress
import math
import os
import ssl
import stat
import threading
import time


_MAX_CA_BYTES = 2097152
_PARTS = ('etc', 'ssl', 'certs', 'ca-certificates.crt')


class PilotTrustUnavailable(Exception):
    def __init__(self):
        super().__init__('Pilot TLS trust unavailable')


class PilotTrustClosureUncertain(Exception):
    pass


def _identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid,
            value.st_gid, value.st_nlink, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


class FixedSystemTrustReader:
    """One fixed bundle, private client context and original IP recipient.

    This deliberately narrower system-bundle scope requires the configured
    endpoint IP to appear in the server certificate's IP SAN. It never tries
    another hostname or CA, consults SSL_CERT_FILE/SSL_CERT_DIR, follows the
    system certificate directory, or falls back to CERT_NONE.
    Original launch must separately control OpenSSL configuration/providers;
    constructing a context here does not qualify their native behavior. Missing/incompatible existing trust refuses.
    No custom CA publication or endpoint policy migration is performed.
    """
    __slots__ = ('_recipient', '_thread', '_end', '_fds', '_states', '_ids',
                 '_opened', '_acquired', '_built', '_taken', '_closed',
                 '_context', '_context_state', '_close_errors', '_close_failure',
                 '_close_refusal')

    def __init__(self, retained_endpoint, original_deadline):
        if (type(retained_endpoint) is not str or
                not 0 < len(retained_endpoint) <= 64 or
                not retained_endpoint.isascii() or '%' in retained_endpoint):
            raise PilotTrustUnavailable()
        try:
            ipaddress.ip_address(retained_endpoint)
        except ValueError:
            raise PilotTrustUnavailable() from None
        if (type(original_deadline) is not float or
                not math.isfinite(original_deadline)):
            raise PilotTrustUnavailable()
        self._recipient = retained_endpoint
        self._thread, self._end = threading.current_thread(), original_deadline
        # Native duties are retained BEFORE the first syscall/context build.
        self._fds = [None] * 5
        self._states = ['unused'] * 5
        self._ids = [None] * 5
        self._opened = self._acquired = self._built = False
        self._taken = self._closed = False
        self._context = None
        self._context_state = 'unused'
        # Pure fixed storage before any FD or SSL acquisition. Actual errors
        # remain private and stable even if an outer close return is lost.
        self._close_errors = [None] * 5
        self._close_failure = None
        self._close_refusal = PilotTrustClosureUncertain()

    def _owner(self):
        if threading.current_thread() is not self._thread:
            raise PilotTrustUnavailable()

    def _current(self):
        if not time.monotonic() < self._end:
            raise PilotTrustUnavailable()

    def _check(self, info, index):
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise PilotTrustUnavailable()
        if index < 4:
            if not stat.S_ISDIR(info.st_mode):
                raise PilotTrustUnavailable()
        elif (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
              not 0 < info.st_size <= _MAX_CA_BYTES):
            raise PilotTrustUnavailable()

    def _open(self, index, flags):
        self._current()
        self._states[index] = 'acquire-pending'
        if index == 0:
            descriptor = os.open('/', flags)
        else:
            descriptor = os.open(_PARTS[index - 1], flags,
                                 dir_fd=self._fds[index - 1])
        self._fds[index] = descriptor
        self._states[index] = 'owned'
        self._current()
        info = os.fstat(descriptor)
        self._check(info, index)
        self._ids[index] = _identity(info)
        self._current()

    def open_fixed(self):
        self._owner()
        if self._opened or self._built or self._closed:
            raise PilotTrustUnavailable()
        self._opened = True
        directories = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            for index in range(5):
                flags = directories if index < 4 else (
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
                self._open(index, flags)
            self._recheck()
            self._acquired = True
        except OSError:
            raise PilotTrustUnavailable() from None

    def _recheck(self):
        self._owner()
        self._current()
        if self._closed or self._states != ['owned'] * 5:
            raise PilotTrustUnavailable()
        for index, descriptor in enumerate(self._fds):
            self._current()
            held = os.fstat(descriptor)
            self._check(held, index)
            if _identity(held) != self._ids[index]:
                raise PilotTrustUnavailable()
            if index:
                self._current()
                named = os.stat(_PARTS[index - 1], dir_fd=self._fds[index - 1],
                                follow_symlinks=False)
                self._check(named, index)
                if _identity(named) != self._ids[index]:
                    raise PilotTrustUnavailable()
            self._current()

    def _bytes(self):
        self._current()
        os.lseek(self._fds[4], 0, os.SEEK_SET)
        self._current()
        raw = bytearray()
        while len(raw) <= _MAX_CA_BYTES:
            self._current()
            piece = os.read(self._fds[4], min(65536, _MAX_CA_BYTES + 1 - len(raw)))
            self._current()
            if not piece:
                break
            raw.extend(piece)
        if len(raw) != self._ids[4][6] or not 0 < len(raw) <= _MAX_CA_BYTES:
            raise PilotTrustUnavailable()
        return bytes(raw)

    def build_private_context(self):
        self._owner()
        if self._closed or not self._acquired or self._built:
            raise PilotTrustUnavailable()
        self._built = True
        try:
            self._recheck()
            raw = self._bytes()
            self._recheck()
            if raw != self._bytes():
                raise PilotTrustUnavailable()
            self._recheck()
            pem = raw.decode('ascii', 'strict')
            self._current()
            self._context_state = 'acquire-pending'
            self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            self._context_state = 'owned'
            self._current()
            self._context.minimum_version = ssl.TLSVersion.TLSv1_2
            self._context.verify_mode = ssl.CERT_REQUIRED
            self._context.check_hostname = True
            # Explicit retained bytes only. No path re-open, default CA paths,
            # environment selector or network/certificate-directory discovery.
            self._context.load_verify_locations(cadata=pem)
            self._current()
            self._recheck()
            self._context_state = 'prepared'
        except (OSError, ValueError, UnicodeError):
            raise PilotTrustUnavailable() from None

    def private_components(self):
        self._owner()
        if (self._closed or self._taken or self._context_state != 'prepared' or
                type(self._context) is not ssl.SSLContext or
                self._context.protocol != ssl.PROTOCOL_TLS_CLIENT or
                self._context.minimum_version < ssl.TLSVersion.TLSv1_2 or
                self._context.verify_mode != ssl.CERT_REQUIRED or
                self._context.check_hostname is not True):
            raise PilotTrustUnavailable()
        self._taken = True
        self._recheck()
        # SAME original context stays retained here and must remain private
        # and immutable in the real owner through all reads/final admission.
        return self._recipient, self._context

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
                self._close_errors[index] = error
                first = self._close_failure
                if (first is None or isinstance(first, Exception) and (
                        not isinstance(error, Exception) or
                        not isinstance(first, MemoryError) and isinstance(error, MemoryError))):
                    self._close_failure = error
            else:
                self._states[index] = 'closed'
        # SSLContext has no explicit close operation. Retain its exact object
        # and any pending build for actual parent process retirement; no flag
        # below claims OpenSSL allocation cleanup or physical closure.
        if self._context_state != 'unused':
            self._context_state = 'retirement-only'
        # Visit every remaining known owned FD before propagating the same
        # first control, then first allocation failure. Never retry uncertain
        # descriptor numbers, clear actual errors or replace a shorter end.
        first = self._close_failure
        if first is not None and (
                not isinstance(first, Exception) or isinstance(first, MemoryError)):
            raise first
        if first is not None or any(s not in ('unused', 'closed') for s in self._states):
            # Preallocated generic refusal avoids exporting native diagnostics
            # or allocating a fresh replacement on each cleanup repetition.
            raise self._close_refusal from None

    def close_observations(self):
        self._owner()
        return tuple(self._states)


# No startup entrypoint, context issuer, native execution or host trust change.
