"""Private original configuration capture; no view or provider authority.

Only an original caller holding its retained source_read may run this attempt.
The caller must retain the attempt before run(). This prefix reads only the
original install root's conf/freq.toml, users.conf and roles.conf. It never calls
load_config, bootstraps, migrates, opens credentials or loads a provider. Root
metadata and equal before/after observations are refusal filters, not absolute
writer exclusion or installation/incarnation proof. External writers remain an
independent positive-admission prerequisite.
"""
import math
import os
import stat
import threading
import time

from freq.core import config, read_source_epoch


_LIMIT = 1048576
_FILES = ('freq.toml', 'users.conf', 'roles.conf')
_SLOTS = 34  # root + at most29 install components + conf + three files


class SourceUnavailable(Exception):
    def __init__(self):
        super().__init__('Read source unavailable')


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _first(first, later):
    if first is None:
        return later
    if not issubclass(type(first), Exception):
        return first
    if not issubclass(type(later), Exception):
        return later
    if not issubclass(type(first), MemoryError) and issubclass(type(later), MemoryError):
        return later
    return first


class ConfigurationCapture:
    """Once-only bounded private file attempt, never an admission capability.

    Unknown open/close returns stay retained. No destructor, automatic retry,
    caller-selected path or supplied acceptance flag can settle those duties.
    Cooperative cutoff checks do not stop an entered syscall or bound RSS.
    Bytes stay private; there is no serializer or diagnostic containing them.
    """
    __slots__ = ('_context', '_end', '_thread', '_started', '_root', '_parts',
                 '_fds', '_states', '_ids', '_errors', '_failure', '_raw',
                 '_directory_count', '_result', '_state', '_completion_failure')

    def __init__(self, context, original_end):
        if (type(context) is not read_source_epoch.source_read
                or type(original_end) not in (int, float)
                or not math.isfinite(original_end)):
            raise SourceUnavailable()
        # No IO or gate acquisition here. Original owner retains this holder
        # before run; all per-file and failure storage precedes acquisitions.
        self._context, self._end = context, original_end
        self._thread = threading.current_thread()
        self._started = False
        self._root = self._parts = None
        self._fds = [None] * _SLOTS
        self._states = ['unused'] * _SLOTS
        self._ids = [None] * _SLOTS
        self._errors = [None] * (_SLOTS + 1)
        self._failure = None
        self._completion_failure = None
        self._raw = [None, None, None]
        self._directory_count = 0
        self._result = None
        self._state = 'prepared'

    def _current(self):
        c = self._context
        if (threading.current_thread() is not self._thread
                or c.thread is not self._thread or c.stage != 'captured'
                or c.rejected or not c._retained
                or read_source_epoch._readers.get(id(c)) is not c
                or read_source_epoch._epoch is not c.epoch
                or not time.monotonic() < self._end):
            raise SourceUnavailable()

    def _check(self, info, directory):
        if info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022:
            raise SourceUnavailable()
        if directory:
            if not stat.S_ISDIR(info.st_mode):
                raise SourceUnavailable()
        elif (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not 0 <= info.st_size <= _LIMIT):
            raise SourceUnavailable()

    def _open(self, index, name, parent, directory, optional=False):
        self._current()
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        flags |= os.O_DIRECTORY if directory else os.O_NONBLOCK
        self._states[index] = 'open-pending'
        try:
            fd = os.open(name, flags, dir_fd=parent)
        except FileNotFoundError:
            # Only these two exact optional file names have absence semantics.
            # No permission/error/timeout is interpreted as an empty source.
            self._states[index] = 'absent'
            if not optional:
                raise
            return
        self._fds[index] = fd
        self._states[index] = 'owned'
        self._current()
        info = os.fstat(fd)
        self._check(info, directory)
        self._ids[index] = _identity(info)

    def _recheck(self):
        self._current()
        if config.resolve_install_dir() != self._root:
            raise SourceUnavailable()
        count = self._directory_count
        for index in range(count + 3):
            self._current()
            if index == 0:
                name, parent = '/', None
            elif index < count:
                name, parent = self._parts[index - 1], self._fds[index - 1]
            else:
                name, parent = _FILES[index - count], self._fds[count - 1]
            if self._states[index] == 'absent':
                try:
                    os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise SourceUnavailable()
            if self._states[index] != 'owned':
                raise SourceUnavailable()
            held = os.fstat(self._fds[index])
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            self._check(held, index < count)
            self._check(named, index < count)
            if _identity(held) != self._ids[index] or _identity(named) != self._ids[index]:
                raise SourceUnavailable()

    def _read(self, index):
        self._current()
        raw = bytearray()
        while len(raw) <= _LIMIT:
            self._current()
            piece = os.read(self._fds[index], min(65536, _LIMIT + 1 - len(raw)))
            self._current()
            if not piece:
                break
            raw.extend(piece)
        if len(raw) > _LIMIT or len(raw) != self._ids[index][6]:
            raise SourceUnavailable()
        return bytes(raw)

    def run(self):
        if self._started or threading.current_thread() is not self._thread:
            raise SourceUnavailable()
        self._started = True
        self._state = 'entered'
        try:
            self._current()
            root = config.resolve_install_dir()
            if (type(root) is not str or not root.startswith('/')
                    or len(root) > 4096 or root == '/'):
                raise SourceUnavailable()
            parts = root[1:].split('/')
            if (not 1 <= len(parts) <= 29
                    or any(not p or p in ('.', '..') or len(os.fsencode(p)) > 255
                           for p in parts)):
                raise SourceUnavailable()
            self._root = root
            self._parts = tuple(parts) + ('conf',)
            self._directory_count = len(self._parts) + 1
            self._open(0, '/', None, True)
            for index, part in enumerate(self._parts, 1):
                self._open(index, part, self._fds[index - 1], True)
            count = self._directory_count
            for offset, name in enumerate(_FILES):
                self._open(count + offset, name, self._fds[count - 1], False, offset > 0)
            self._recheck()
            for offset in range(3):
                if self._states[count + offset] == 'owned':
                    self._raw[offset] = self._read(count + offset)
            self._recheck()
            result = tuple(self._raw)
        except BaseException as failure:
            self._errors[0] = failure
        # Independent reverse close attempts precede exception classification.
        # Unknown acquisitions without a returned FD cannot be guessed closed.
        for index in range(_SLOTS - 1, -1, -1):
            if self._states[index] != 'owned':
                continue
            self._states[index] = 'close-pending'
            try:
                os.close(self._fds[index])
            except BaseException as failure:
                self._errors[index + 1] = failure
            else:
                self._states[index] = 'closed'
        # Unknown completion bookkeeping cannot publish success or erase an
        # earlier body/close failure. All independent closes already ran.
        self._state = 'unsettled'
        try:
            self._state = ('unsettled' if any(s in ('open-pending', 'close-pending')
                           for s in self._states) else 'closed')
            if all(failure is None for failure in self._errors):
                try:
                    self._current()  # No late publication after known cleanup.
                except BaseException as failure:
                    self._errors[0] = failure
        except BaseException as failure:
            self._completion_failure = failure
            self._state = 'unsettled'
        # Body first, then actual reverse-close order; retain first identity
        # within each priority class after every independent close attempt.
        for offset in range(_SLOTS + 1):
            index = 0 if offset == 0 else _SLOTS + 1 - offset
            failure = self._errors[index]
            if failure is not None:
                self._failure = _first(self._failure, failure)
        if self._completion_failure is not None:
            self._failure = _first(self._failure, self._completion_failure)
        if self._failure is not None:
            failure = self._failure
            if not issubclass(type(failure), Exception) or issubclass(type(failure), MemoryError):
                raise failure from None
            raise SourceUnavailable() from None
        self._result = result
        return result
