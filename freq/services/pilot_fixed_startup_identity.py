"""Fixed startup configured identity sources; uninstalled native source.

This reads existing freq.toml and optional users.conf/roles.conf only. It never
selects a Vault, machine identity, password hash or node token credential file.
The original owner retains this object before effects and owes actual source,
principal, all-writer exclusion, native deadline/resources and physical cleanup.
All returned bytes and metadata remain private DATA, never an issuer.
"""
import math
import os
import stat
import threading
import time


_MIB = 1048576
# Every parent is an original held descriptor. No cwd, environment, request,
# configuration-selected path, legacy loader or alternate location is used.
_PARENTS = (None, 0, 1, 2, 3, 3, 3)
_NAMES = ('/', 'opt', 'pve-freq', 'conf', 'freq.toml', 'users.conf',
          'roles.conf')
_DIRECTORIES = frozenset((0, 1, 2, 3))
_OPTIONAL = frozenset((5, 6))
_FILES = (4, 5, 6)


class PilotStartupIdentityUnavailable(Exception):
    def __init__(self):
        super().__init__('Pilot startup identity sources unavailable')


class PilotStartupIdentityClosureUncertain(Exception):
    def __init__(self):
        super().__init__('Pilot startup identity cleanup unresolved')


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _first_close_failure(first, later):
    if (first is None or
            (isinstance(first, Exception) and not isinstance(later, Exception)) or
            (isinstance(first, Exception) and not isinstance(first, MemoryError) and
             isinstance(later, MemoryError))):
        return later
    return first


class FixedStartupIdentityReader:
    """One original thread and end; existing configured identity bytes only.

    Native-confirmed absence alone is None; empty-present files stay bytes.
    source_uid is native expected DATA, never principal/writer authority.
    """
    __slots__ = ('_source_uid', '_end', '_thread', '_fds', '_states', '_ids',
                 '_started', '_read', '_closed', '_close_errors', '_close_failure',
                 '_initialization_spent')

    def __init__(self, source_uid, original_deadline):
        if (type(self) is not FixedStartupIdentityReader or
                hasattr(self, '_initialization_spent')):
            raise PilotStartupIdentityUnavailable()
        if (type(source_uid) is not int or
                not 1 <= source_uid <= 4294967294 or
                type(original_deadline) is not float or
                not math.isfinite(original_deadline)):
            raise PilotStartupIdentityUnavailable()
        # Spend before fallible thread/holder storage; retained duties are never
        # replaced by a repeated or partially completed initialization.
        self._initialization_spent = True
        self._source_uid, self._end = source_uid, original_deadline
        self._thread = threading.current_thread()
        self._fds, self._states, self._ids = [None]*7, ['unused']*7, [None]*7
        self._started = self._read = self._closed = False
        # Persistent holders exist before any later native acquisition.
        self._close_errors, self._close_failure = [None]*7, None

    def _owner(self):
        if threading.current_thread() is not self._thread:
            raise PilotStartupIdentityUnavailable()

    def _current(self):
        if not time.monotonic() < self._end:
            raise PilotStartupIdentityUnavailable()

    def _check(self, info, index):
        directory = index in _DIRECTORIES
        uid = self._source_uid if index in (3, 4, 5, 6) else 0
        if (info.st_uid != uid or info.st_mode & 0o022 or
                (not stat.S_ISDIR(info.st_mode) if directory
                 else not stat.S_ISREG(info.st_mode))):
            raise PilotStartupIdentityUnavailable()
        if not directory:
            minimum = 1 if index == 4 else 0
            if info.st_nlink != 1 or not minimum <= info.st_size <= _MIB:
                raise PilotStartupIdentityUnavailable()

    def _open(self, index):
        self._current()
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
        flags |= os.O_DIRECTORY if index in _DIRECTORIES else os.O_NONBLOCK
        # Pending BEFORE the syscall, not in a wrapper that receives its result.
        # A lost return remains unresolved and cannot be counted as unused.
        self._states[index] = 'acquire-pending'
        try:
            if index == 0:
                descriptor = os.open('/', flags)
            else:
                descriptor = os.open(_NAMES[index], flags,
                                     dir_fd=self._fds[_PARENTS[index]])
        except FileNotFoundError:
            if index not in _OPTIONAL:
                raise PilotStartupIdentityUnavailable() from None
            # Only an explicit native ENOENT for this exact optional leaf may
            # become None. Access denial, symlink/IO failure and lost return do
            # not become a successful missing users/roles input.
            self._states[index] = 'absent'
            self._current()
            return
        self._fds[index] = descriptor
        self._states[index] = 'owned'
        self._current()
        info = os.fstat(descriptor)
        self._check(info, index)
        self._ids[index] = _identity(info)
        self._current()

    def open_fixed(self):
        self._owner()
        if self._started or self._closed:
            raise PilotStartupIdentityUnavailable()
        self._started = True
        for index in range(7):
            self._open(index)
        # All three metadata/absence checks precede every source byte.
        total = sum(self._ids[i][6] for i in _FILES
                    if self._states[i] == 'owned')
        if total > 3 * _MIB:
            raise PilotStartupIdentityUnavailable()
        self._recheck()

    def _recheck(self):
        self._owner()
        self._current()
        if self._closed:
            raise PilotStartupIdentityUnavailable()
        for index in range(7):
            state = self._states[index]
            if state == 'absent' and index in _OPTIONAL:
                try:
                    os.stat(_NAMES[index], dir_fd=self._fds[_PARENTS[index]],
                            follow_symlinks=False)
                except FileNotFoundError:
                    self._current()
                    continue
                raise PilotStartupIdentityUnavailable()
            if state != 'owned':
                raise PilotStartupIdentityUnavailable()
            self._current()
            held = os.fstat(self._fds[index])
            self._check(held, index)
            if _identity(held) != self._ids[index]:
                raise PilotStartupIdentityUnavailable()
            if index:
                self._current()
                named = os.stat(_NAMES[index], dir_fd=self._fds[_PARENTS[index]],
                                follow_symlinks=False)
                self._check(named, index)
                if _identity(named) != self._ids[index]:
                    raise PilotStartupIdentityUnavailable()
            self._current()

    def _bytes(self, index):
        if self._states[index] == 'absent' and index in _OPTIONAL:
            return None
        self._current()
        os.lseek(self._fds[index], 0, os.SEEK_SET)
        maximum = _MIB
        result = bytearray()
        while True:
            self._current()
            # One overflow sentinel; extend only after testing remaining cap.
            chunk = os.read(self._fds[index], min(16384, maximum - len(result) + 1))
            self._current()
            if not chunk:
                break
            if len(chunk) > maximum - len(result):
                raise PilotStartupIdentityUnavailable()
            result.extend(chunk)
        if len(result) != self._ids[index][6]:
            raise PilotStartupIdentityUnavailable()
        return bytes(result)

    def read_inputs(self):
        self._owner()
        if not self._started or self._read or self._closed:
            raise PilotStartupIdentityUnavailable()
        self._read = True
        self._recheck()
        first = tuple(self._bytes(i) for i in _FILES)
        self._recheck()
        second = tuple(self._bytes(i) for i in _FILES)
        self._recheck()
        if first != second:
            raise PilotStartupIdentityUnavailable()
        # Exact order: freq.toml, optional users.conf, optional roles.conf.
        # Configuration bytes remain private and may contain sensitive values.
        return first

    def close(self):
        self._owner()
        self._closed = True
        for index in range(6, -1, -1):
            if self._states[index] != 'owned':
                continue
            self._states[index] = 'close-attempted'
            try:
                os.close(self._fds[index])
            except BaseException as error:
                self._close_errors[index] = error
                self._states[index] = 'uncertain'
                self._close_failure = _first_close_failure(self._close_failure, error)
            else:
                self._states[index] = 'closed'
        failure = self._close_failure
        if failure is not None and (not isinstance(failure, Exception) or isinstance(failure, MemoryError)):
            raise failure
        if failure is not None or any(state not in ('unused', 'absent', 'closed') for state in self._states):
            raise PilotStartupIdentityClosureUncertain() from None
        # Local known-FD completion never proves outside native retirement.

    def cleanup_observations(self):
        self._owner()
        return tuple(self._states)


# No native launch, credential reads, issuer, defaults or positive factory.
