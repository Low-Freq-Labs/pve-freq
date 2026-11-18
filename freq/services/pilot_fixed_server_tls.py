"""Fixed existing pilot server certificate and key acquisition, uninstalled.

The actual original owner must retain the native process, principal, immutable
runtime, /proc view and exclusion of every certificate/key/source writer before
calling this leaf. Metadata and equal reads only refuse discrepancies; they
cannot establish those conditions. No file, trust store or service is changed.
"""
import math
import os
import ssl
import stat
import threading
import time


_NAMES = ('etc', 'freq', 'tls', 'cert.pem', 'key.pem')
_PARENTS = (None, 0, 1, 2, 3, 3)
_CERT_CAP = 1048576
_KEY_CAP = 65536


class PilotServerTLSUnavailable(Exception):
    def __init__(self):
        super().__init__('Pilot server TLS unavailable')


class PilotServerTLSClosureUncertain(Exception):
    pass


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
            info.st_gid, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _first(first, later):
    if later is None:
        return first
    if (first is None or
            (isinstance(first, Exception) and not isinstance(later, Exception)) or
            (isinstance(first, Exception) and not isinstance(first, MemoryError) and
             isinstance(later, MemoryError))):
        return later
    return first


class FixedServerTLSReader:
    """Six original FD slots and one retained server context build duty.

    Only /etc/freq/tls/cert.pem and /etc/freq/tls/key.pem are selected. These
    spellings come from the existing configuration example, not a claim that
    they exist or that their actual acquisition is authorized or qualified.
    credential_uid is original-owner DATA, never a caller credential grant.
    The native parent owns hard bounds, lost calls and physical key retirement.
    """
    __slots__ = ('_uid', '_end', '_thread', '_fds', '_states', '_ids',
                 '_opened', '_acquired', '_built', '_closed', '_taken',
                 '_context', '_context_state',
                 '_initialization_spent', '_close_errors', '_close_failure')

    def __init__(self, credential_uid, original_deadline):
        if type(self) is not FixedServerTLSReader or hasattr(self, '_initialization_spent'):
            raise PilotServerTLSUnavailable()
        if (type(credential_uid) is not int or not 0 < credential_uid < 2**31 or
                type(original_deadline) is not float or
                not math.isfinite(original_deadline)):
            raise PilotServerTLSUnavailable()
        # Spend initialization before thread/descriptor holder allocations.
        self._initialization_spent = True
        self._close_errors = [None] * 6
        self._close_failure = None
        self._uid, self._end = credential_uid, original_deadline
        self._thread = threading.current_thread()
        # Retain duties before the first fallible syscall or context build.
        self._fds, self._states, self._ids = [None]*6, ['unused']*6, [None]*6
        self._opened = self._acquired = self._built = False
        self._closed = self._taken = False
        self._context, self._context_state = None, 'unused'

    def _owner(self):
        if threading.current_thread() is not self._thread:
            raise PilotServerTLSUnavailable()

    def _current(self):
        if not time.monotonic() < self._end:
            raise PilotServerTLSUnavailable()

    def _check(self, info, index):
        if index < 4:
            if (info.st_uid != 0 or info.st_mode & 0o022 or
                    not stat.S_ISDIR(info.st_mode)):
                raise PilotServerTLSUnavailable()
        else:
            cap = _CERT_CAP if index == 4 else _KEY_CAP
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    not 0 < info.st_size <= cap):
                raise PilotServerTLSUnavailable()
            if index == 4:
                if info.st_uid != 0 or info.st_mode & 0o022:
                    raise PilotServerTLSUnavailable()
            elif info.st_uid != self._uid or stat.S_IMODE(info.st_mode) != 0o600:
                raise PilotServerTLSUnavailable()

    def _open(self, index, flags):
        self._current()
        self._states[index] = 'acquire-pending'
        if index == 0:
            descriptor = os.open('/', flags)
        else:
            descriptor = os.open(_NAMES[index-1], flags,
                                 dir_fd=self._fds[_PARENTS[index]])
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
            raise PilotServerTLSUnavailable()
        self._opened = True
        try:
            for index in range(6):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
                flags |= os.O_DIRECTORY if index < 4 else os.O_NONBLOCK
                self._open(index, flags)
            self._recheck()
            self._acquired = True
        except OSError:
            raise PilotServerTLSUnavailable() from None

    def _recheck(self):
        self._owner()
        self._current()
        if self._closed or self._states != ['owned']*6:
            raise PilotServerTLSUnavailable()
        for index, descriptor in enumerate(self._fds):
            self._current()
            held = os.fstat(descriptor)
            self._check(held, index)
            if _identity(held) != self._ids[index]:
                raise PilotServerTLSUnavailable()
            if index:
                self._current()
                named = os.stat(_NAMES[index-1],
                                dir_fd=self._fds[_PARENTS[index]],
                                follow_symlinks=False)
                self._check(named, index)
                if _identity(named) != self._ids[index]:
                    raise PilotServerTLSUnavailable()
            self._current()

    def _bytes(self, index, cap):
        self._current()
        os.lseek(self._fds[index], 0, os.SEEK_SET)
        self._current()
        raw = bytearray()
        while len(raw) <= cap:
            self._current()
            piece = os.read(self._fds[index], min(65536, cap+1-len(raw)))
            self._current()
            if not piece:
                break
            raw.extend(piece)
        if len(raw) != self._ids[index][6] or not 0 < len(raw) <= cap:
            raise PilotServerTLSUnavailable()
        return bytes(raw)

    def build_private_context(self):
        self._owner()
        if self._closed or not self._acquired or self._built:
            raise PilotServerTLSUnavailable()
        self._built = True
        try:
            self._recheck()
            cert, key = self._bytes(4, _CERT_CAP), self._bytes(5, _KEY_CAP)
            self._recheck()
            if cert != self._bytes(4, _CERT_CAP) or key != self._bytes(5, _KEY_CAP):
                raise PilotServerTLSUnavailable()
            self._recheck()
            # Narrow PEM refusal filters, not an independent crypto parser.
            if (b'-----BEGIN CERTIFICATE-----' not in cert or
                    b'PRIVATE KEY' in cert or b'ENCRYPTED' in key or
                    b'Proc-Type:' in key or b'DEK-Info:' in key or
                    b'-----BEGIN ' not in key or b'PRIVATE KEY-----' not in key):
                raise PilotServerTLSUnavailable()
            self._current()
            self._context_state = 'acquire-pending'
            self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self._context_state = 'owned'
            self._current()
            self._context.minimum_version = ssl.TLSVersion.TLSv1_2
            # CPython accepts paths only. These private spellings refer to the
            # SAME retained original descriptors; no configuration path, file
            # copy, temporary key or caller callback is accepted. Native owner
            # must enforce the actual /proc view and writer exclusion through
            # OpenSSL's descriptor reopens and all use of the retained context.
            self._current()
            self._context.load_cert_chain(
                '/proc/self/fd/' + str(self._fds[4]),
                '/proc/self/fd/' + str(self._fds[5]), password=b'')
            self._current()
            self._recheck()
            # Read equality does not prevent ABA or establish immutable backing.
            if cert != self._bytes(4, _CERT_CAP) or key != self._bytes(5, _KEY_CAP):
                raise PilotServerTLSUnavailable()
            self._recheck()
            self._context_state = 'prepared'
        except (OSError, ValueError):
            raise PilotServerTLSUnavailable() from None

    def private_context(self):
        self._owner()
        if (self._closed or self._taken or self._context_state != 'prepared' or
                type(self._context) is not ssl.SSLContext or
                self._context.protocol != ssl.PROTOCOL_TLS_SERVER or
                self._context.minimum_version < ssl.TLSVersion.TLSv1_2):
            raise PilotServerTLSUnavailable()
        self._recheck()
        self._taken = True
        # SAME context stays strongly retained here. Actual owner must keep it
        # private and immutable until original physical parent retirement.
        return self._context

    def close(self):
        self._owner()
        self._closed = True
        first = None
        for index in range(5, -1, -1):
            if self._states[index] != 'owned':
                continue
            self._states[index] = 'close-attempted'
            try:
                os.close(self._fds[index])
            except BaseException as error:
                self._close_errors[index] = error
                self._states[index] = 'uncertain'
                first = _first(first, error)
            else:
                self._states[index] = 'closed'
        # No explicit SSLContext close exists. Retain exact context/pending
        # build for actual physical process retirement, including after local
        # descriptor closure. No retry of uncertain descriptor numbers.
        if self._context_state != 'unused':
            self._context_state = 'retirement-only'
        self._close_failure = _first(self._close_failure, first)
        # The persistent winner also governs repeated retirement. A repeat
        # never re-closes uncertain slots or demotes the original protected error.
        failure = self._close_failure
        if failure is not None and (not isinstance(failure, Exception) or isinstance(failure, MemoryError)):
            raise failure
        if failure is not None or any(s not in ('unused', 'closed') for s in self._states):
            raise PilotServerTLSClosureUncertain() from None

    def close_observations(self):
        self._owner()
        return tuple(self._states)


# No startup entrypoint, listener construction, certificate provisioning or
# positive installation issuer. New native cases remain unimplemented/unrun.
