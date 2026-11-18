"""Fixed existing CA/per-node token read attempts, never provider authority.

Original callers retain attempts/capacity before run, under their actual owned
source_read and original cutoff. Only enumerated existing files are read; no
new trust, secret, account, permissions or provider is installed. Equal metadata
and process/NSS observations are refusal filters, not external-writer exclusion,
installation/target identity or a grant. No HTTP caller is joined in this stage.
"""
import hashlib
import ipaddress
import math
import os
import re
import stat
import threading
import time

from freq.core import read_source_epoch
from freq.services.standard_qemu_runtime_identity import RuntimeIdentityCapture


class PrivateSourceUnavailable(Exception):
    def __init__(self):
        super().__init__('Read private source unavailable')


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _first(first, later):
    if first is None or issubclass(type(first), Exception) and (
            not issubclass(type(later), Exception)
            or not issubclass(type(first), MemoryError) and issubclass(type(later), MemoryError)):
        return later
    return first


class _FixedFileCapture:
    __slots__ = ('_context', '_end', '_parts', '_cap', '_group', '_runtime',
                 '_thread', '_used', '_fds', '_stages', '_ids', '_errors',
                 '_failure', '_state', '_result', '_authorization_prefix',
                 '_completion_failure')

    def _prepare(self, context, original_end, parts, cap, runtime=None):
        if hasattr(self, '_used'):
            raise PrivateSourceUnavailable()
        if (type(context) is not read_source_epoch.source_read
                or type(original_end) not in (int, float)
                or not math.isfinite(original_end)):
            raise PrivateSourceUnavailable()
        self._context, self._end, self._parts, self._cap = context, original_end, parts, cap
        self._runtime = runtime
        self._group = None if runtime is None else runtime._result[4]
        self._authorization_prefix = None
        self._thread = threading.current_thread()
        self._used = False
        self._fds = [None] * 5
        self._stages = ['unused'] * 5
        self._ids = [None] * 5
        self._errors = [None] * 6
        self._failure = self._result = None
        self._completion_failure = None
        self._state = 'prepared'

    def _current(self):
        c = self._context
        if (threading.current_thread() is not self._thread
                or c.thread is not self._thread or c.stage != 'captured'
                or c.rejected or not c._retained
                or read_source_epoch._readers.get(id(c)) is not c
                or read_source_epoch._epoch is not c.epoch
                or not time.monotonic() < self._end):
            raise PrivateSourceUnavailable()
        if self._runtime is not None and (self._runtime._context is not c
                or self._runtime._state != 'closed' or self._runtime._result is None
                or self._runtime._end != self._end):
            raise PrivateSourceUnavailable()

    def _check(self, info, index):
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise PrivateSourceUnavailable()
        if index < 4:
            if not stat.S_ISDIR(info.st_mode):
                raise PrivateSourceUnavailable()
        elif (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not 0 < info.st_size <= self._cap
                or self._runtime is not None and (
                    stat.S_IMODE(info.st_mode) != 0o640
                    or info.st_gid != self._group or info.st_size not in (36, 37))):
            raise PrivateSourceUnavailable()

    def _open(self, index):
        self._current()
        self._stages[index] = 'open-pending'
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        flags |= os.O_DIRECTORY if index < 4 else os.O_NONBLOCK
        try:
            fd = os.open('/', flags) if index == 0 else os.open(
                self._parts[index - 1], flags, dir_fd=self._fds[index - 1])
        except FileNotFoundError:
            self._stages[index] = 'absent'
            raise
        self._fds[index] = fd
        self._stages[index] = 'owned'
        self._current()
        info = os.fstat(fd)
        self._check(info, index)
        self._ids[index] = _identity(info)

    def _recheck(self):
        for index in range(5):
            self._current()
            if self._stages[index] != 'owned':
                raise PrivateSourceUnavailable()
            held = os.fstat(self._fds[index])
            named = os.stat('/', follow_symlinks=False) if index == 0 else os.stat(
                self._parts[index - 1], dir_fd=self._fds[index - 1], follow_symlinks=False)
            self._check(held, index)
            self._check(named, index)
            if _identity(held) != self._ids[index] or _identity(named) != self._ids[index]:
                raise PrivateSourceUnavailable()

    def _read(self):
        raw = bytearray()
        while len(raw) <= self._cap:
            self._current()
            piece = os.read(self._fds[4], min(65536, self._cap + 1 - len(raw)))
            self._current()
            if not piece:
                break
            raw.extend(piece)
        if not 0 < len(raw) <= self._cap or len(raw) != self._ids[4][6]:
            raise PrivateSourceUnavailable()
        return bytes(raw)

    def run(self):
        if self._used or threading.current_thread() is not self._thread:
            raise PrivateSourceUnavailable()
        self._used = True
        self._state = 'entered'
        try:
            for index in range(5):
                self._open(index)
            self._recheck()
            raw = self._read()
            self._recheck()
            if self._runtime is None:
                raw.decode('ascii', 'strict')  # Native TLS still validates CA syntax.
                result = raw
            else:
                secret = raw[:-1] if len(raw) == 37 and raw[-1] == 10 else raw
                if not re.fullmatch(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', secret):
                    raise PrivateSourceUnavailable()
                result = self._authorization_prefix + secret
        except BaseException as failure:
            self._errors[0] = failure
        # Retain raw failures; attempt every independent known close first.
        for index in range(4, -1, -1):
            if self._stages[index] != 'owned':
                continue
            self._stages[index] = 'close-pending'
            try:
                os.close(self._fds[index])
            except BaseException as failure:
                self._errors[index + 1] = failure
            else:
                self._stages[index] = 'closed'
        # Unknown completion bookkeeping cannot publish success or erase an
        # earlier body/close failure. All independent closes already ran.
        self._state = 'unsettled'
        try:
            self._state = ('unsettled' if any(stage in ('open-pending', 'close-pending')
                           for stage in self._stages) else 'closed')
            if all(failure is None for failure in self._errors):
                try:
                    self._current()
                except BaseException as failure:
                    self._errors[0] = failure
        except BaseException as failure:
            self._completion_failure = failure
            self._state = 'unsettled'
        for index in (0, 5, 4, 3, 2, 1):
            failure = self._errors[index]
            if failure is not None:
                self._failure = _first(self._failure, failure)
        if self._completion_failure is not None:
            self._failure = _first(self._failure, self._completion_failure)
        if self._failure is not None:
            failure = self._failure
            if not issubclass(type(failure), Exception) or issubclass(type(failure), MemoryError):
                raise failure from None
            raise PrivateSourceUnavailable() from None
        self._result = result
        return result


class SystemTrustCapture(_FixedFileCapture):
    __slots__ = ()

    def __init__(self, context, original_end):
        if type(self) is not SystemTrustCapture:
            raise PrivateSourceUnavailable()
        self._prepare(context, original_end,
                      ('etc', 'ssl', 'certs', 'ca-certificates.crt'), 1048576)


class NodeTokenCapture(_FixedFileCapture):
    __slots__ = ()

    def __init__(self, context, original_end, runtime, configured_endpoint, configured_principal):
        if type(self) is not NodeTokenCapture:
            raise PrivateSourceUnavailable()
        if (type(runtime) is not RuntimeIdentityCapture
                or runtime._state != 'closed' or runtime._result is None
                or runtime._context is not context or runtime._end != original_end
                or type(configured_endpoint) is not str
                or not 0 < len(configured_endpoint) <= 45 or not configured_endpoint.isascii()
                or '%' in configured_endpoint
                or type(configured_principal) is not str
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}@[A-Za-z0-9_.-]{1,128}', configured_principal)):
            raise PrivateSourceUnavailable()
        try:
            address = ipaddress.ip_address(configured_endpoint)
        except ValueError:
            raise PrivateSourceUnavailable() from None
        if address.is_unspecified or address.is_multicast:
            raise PrivateSourceUnavailable()
        # Match original _pve_node_token_suffix spelling; transport IP
        # normalization cannot substitute a different credential-file identity.
        suffix = hashlib.sha256(configured_endpoint.encode('ascii')).hexdigest()[:12]
        self._prepare(context, original_end,
                      ('etc', 'freq', 'credentials', 'pve-token-rw-' + suffix), 37, runtime)
        self._authorization_prefix = ('PVEAPIToken=' + configured_principal
                                     + '!freq-rw-' + suffix + '=').encode('ascii')
