"""Fixed four startup source files under original native owner custody.

Uninstalled source only. The outer actual owner retains original source/code,
principal, namespace, all-writer fence and pending native operations through
physical retirement. Equal data and metadata never establish that authority.
"""
import math
import os
import stat
import threading
import time


_NAMES = ('opt', 'pve-freq', 'conf', 'freq.toml', 'hosts.toml',
          'vlans.toml', 'fleet-boundaries.toml')
_PARENTS = (None, 0, 1, 2, 3, 3, 3, 3)
_MIB = 1048576
_LIMITS = (2*_MIB, 2*_MIB, 2*_MIB, _MIB)


class PilotStartupSourcesUnavailable(Exception):
    def __init__(self):
        super().__init__('Pilot startup sources unavailable')


class PilotStartupSourcesClosureUncertain(Exception):
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


class FixedStartupSourceReader:
    """Eight retained FD duties; complete config cohort bytes remain DATA.

    Fixed /opt/pve-freq/conf source files and UID/mode/caps follow the original
    accepted four-source reader. Empty native-present files stay empty. Missing
    files refuse; no defaults, host reads selected by configuration or writes.
    All parsing/final native admission remain outside this leaf.
    """
    __slots__ = ('_uid', '_end', '_thread', '_fds', '_states', '_ids',
                 '_opened', '_acquired', '_read', '_closed',
                 '_initialization_spent', '_close_errors', '_close_failure')

    def __init__(self, source_uid, original_deadline):
        if type(self) is not FixedStartupSourceReader or hasattr(self, '_initialization_spent'):
            raise PilotStartupSourcesUnavailable()
        if (type(source_uid) is not int or not 1 <= source_uid <= 4294967294 or
                type(original_deadline) is not float or
                not math.isfinite(original_deadline)):
            raise PilotStartupSourcesUnavailable()
        # Spend initialization before thread/descriptor holder allocations.
        self._initialization_spent = True
        self._close_errors = [None] * 8
        self._close_failure = None
        self._uid, self._end = source_uid, original_deadline
        self._thread = threading.current_thread()
        # Retain duties before the first fallible native syscall.
        self._fds, self._states, self._ids = [None]*8, ['unused']*8, [None]*8
        self._opened = self._acquired = self._read = False
        self._closed = False

    def _owner(self):
        if threading.current_thread() is not self._thread:
            raise PilotStartupSourcesUnavailable()

    def _current(self):
        if not time.monotonic() < self._end:
            raise PilotStartupSourcesUnavailable()

    def _check(self, info, index):
        expected_uid = 0 if index < 3 else self._uid
        if info.st_uid != expected_uid or info.st_mode & 0o022:
            raise PilotStartupSourcesUnavailable()
        if index < 4:
            if not stat.S_ISDIR(info.st_mode):
                raise PilotStartupSourcesUnavailable()
        elif (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
              not 0 <= info.st_size <= _LIMITS[index-4]):
            raise PilotStartupSourcesUnavailable()

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
        if self._opened or self._read or self._closed:
            raise PilotStartupSourcesUnavailable()
        self._opened = True
        try:
            for index in range(8):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
                flags |= os.O_DIRECTORY if index < 4 else os.O_NONBLOCK
                self._open(index, flags)
            # Whole first-three config allowance precedes any byte read.
            if sum(self._ids[i][6] for i in (4, 5, 6)) > 4*_MIB:
                raise PilotStartupSourcesUnavailable()
            self._recheck()
            self._acquired = True
        except OSError:
            raise PilotStartupSourcesUnavailable() from None

    def _recheck(self):
        self._owner()
        self._current()
        if self._closed or self._states != ['owned']*8:
            raise PilotStartupSourcesUnavailable()
        for index, descriptor in enumerate(self._fds):
            self._current()
            held = os.fstat(descriptor)
            self._check(held, index)
            if _identity(held) != self._ids[index]:
                raise PilotStartupSourcesUnavailable()
            if index:
                self._current()
                named = os.stat(_NAMES[index-1],
                                dir_fd=self._fds[_PARENTS[index]],
                                follow_symlinks=False)
                self._check(named, index)
                if _identity(named) != self._ids[index]:
                    raise PilotStartupSourcesUnavailable()
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
        if len(raw) != self._ids[index][6] or not 0 <= len(raw) <= cap:
            raise PilotStartupSourcesUnavailable()
        return bytes(raw)

    def read_sources(self):
        self._owner()
        if self._closed or not self._acquired or self._read:
            raise PilotStartupSourcesUnavailable()
        self._read = True
        try:
            self._recheck()
            first = tuple(self._bytes(i, _LIMITS[i-4]) for i in range(4, 8))
            self._recheck()
            second = tuple(self._bytes(i, _LIMITS[i-4]) for i in range(4, 8))
            self._recheck()
            if first != second:
                raise PilotStartupSourcesUnavailable()
            # Exact bytes only; independently supervised fixed parsers and the
            # original native owner determine later eligibility/currentness.
            return first
        except OSError:
            raise PilotStartupSourcesUnavailable() from None

    def close(self):
        self._owner()
        self._closed = True
        first = None
        for index in range(7, -1, -1):
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
        # Unknown native open/stat/read/close work remains a physical parent
        # duty even if every locally known descriptor has closed. No numeric
        # retry, renewed deadline or false closure from a local state tuple.
        self._close_failure = _first(self._close_failure, first)
        # The persistent winner also governs repeated retirement. A repeat
        # never re-closes uncertain slots or demotes the original protected error.
        failure = self._close_failure
        if failure is not None and (not isinstance(failure, Exception) or isinstance(failure, MemoryError)):
            raise failure
        if failure is not None or any(s not in ('unused', 'closed') for s in self._states):
            raise PilotStartupSourcesClosureUncertain() from None

    def close_observations(self):
        self._owner()
        return tuple(self._states)


# No original native factory/issuer, parser, profile or installed activation.
