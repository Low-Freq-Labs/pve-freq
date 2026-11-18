"""Uninstalled fixed six-file retention leaf; returned values are private DATA.

The outside original owner must retain this same object before acquisition and
retain actual source/code/principal/namespace/all-writer/end/physical duties.
Repeated metadata/absence checks never establish those gates. No caller path,
callback, parser, native observation, issuer or positive admission is accepted.
"""
import errno
import math
import os
import stat
import threading
import time


_MIB = 1048576
_NAMES = ('/', 'opt', 'pve-freq', 'conf', 'freq.toml', 'hosts.toml',
          'vlans.toml', 'fleet-boundaries.toml', 'distros.toml',
          'network-profiles.toml')
_PARENTS = (None, 0, 1, 2, 3, 3, 3, 3, 3, 3)
_LIMITS = (2*_MIB, 2*_MIB, 2*_MIB, _MIB, _MIB, _MIB)


class OptionsSourcesUnavailable(Exception):
    def __init__(self):
        super().__init__('VM options sources unavailable')


class OptionsSourcesClosureUncertain(Exception):
    def __init__(self):
        super().__init__('VM options source cleanup unresolved')


def _first(first, later):
    if later is None:
        return first
    if (first is None or
            (isinstance(first, Exception) and not isinstance(later, Exception)) or
            (isinstance(first, Exception) and not isinstance(first, MemoryError) and
             isinstance(later, MemoryError))):
        return later
    return first


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
            info.st_gid, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


class FixedOptionsSourceReader:
    """Ten fixed descriptor duties, six byte entries, one thread and end.

Only a known exact optional ENOENT may become absent-observed; every complete
cohort check repeats its named no-follow absence check under the same conf FD.
Returned None is copyable DATA, not authenticated absence or source authority.
Existing four-file startup reader and parser remain separate and unchanged.
"""
    __slots__ = ('_uid', '_end', '_thread', '_initialization_spent',
                 '_fds', '_states', '_ids', '_close_errors', '_close_failure',
                 '_buffers', '_chunks', '_results', '_body_failure',
                 '_held_results', '_named_results', '_absence_errors',
                 '_opened', '_acquired', '_read', '_closed', '_failed')

    def __init__(self, source_uid, original_deadline):
        if type(self) is not FixedOptionsSourceReader or hasattr(self, '_initialization_spent'):
            raise OptionsSourcesUnavailable()
        # Spend before fallible validation/holder allocations; never restart.
        self._initialization_spent = True
        if (type(source_uid) is not int or not 1 <= source_uid <= 4294967294 or
                type(original_deadline) is not float or not math.isfinite(original_deadline)):
            raise OptionsSourcesUnavailable()
        self._uid, self._end = source_uid, original_deadline
        self._thread = threading.current_thread()
        self._fds, self._states, self._ids = [None]*10, ['unused']*10, [None]*10
        self._close_errors, self._close_failure = [None]*10, None
        self._held_results, self._named_results, self._absence_errors = [None]*10, [None]*10, [None]*10
        # Both pass holders are retained before any native acquisition. Partial
        # bytearrays, last returned chunks and complete results survive failure.
        self._buffers = ([None]*6, [None]*6)
        self._chunks = ([None]*6, [None]*6)
        self._results = ([None]*6, [None]*6)
        self._body_failure = None
        self._opened = self._acquired = self._read = self._closed = self._failed = False

    def _owner(self):
        if threading.current_thread() is not self._thread:
            raise OptionsSourcesUnavailable()

    def _current(self):
        if not time.monotonic() < self._end:
            raise OptionsSourcesUnavailable()

    def _check(self, info, index):
        uid = 0 if index < 3 else self._uid
        if info.st_uid != uid or info.st_mode & 0o022:
            raise OptionsSourcesUnavailable()
        if index < 4:
            if not stat.S_ISDIR(info.st_mode):
                raise OptionsSourcesUnavailable()
        elif (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
              not 0 <= info.st_size <= _LIMITS[index-4]):
            raise OptionsSourcesUnavailable()

    def _open(self, index):
        self._current()
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        flags |= os.O_DIRECTORY if index < 4 else os.O_NONBLOCK
        self._states[index] = 'acquire-pending'
        try:
            if index == 0:
                descriptor = os.open('/', flags)
            else:
                descriptor = os.open(_NAMES[index], flags,
                                     dir_fd=self._fds[_PARENTS[index]])
        except OSError as error:
            if index < 8 or error.errno != errno.ENOENT:
                raise
            # Known result retained before the post-call end check. No FD is
            # invented; unknown open return must remain acquire-pending.
            self._absence_errors[index] = error
            self._states[index] = 'absent-observed'
            self._current()
            return
        self._fds[index] = descriptor
        self._states[index] = 'owned'
        self._current()
        info = os.fstat(descriptor)
        self._held_results[index] = info
        self._current()
        self._check(info, index)
        self._ids[index] = _identity(info)
        self._current()

    def open_fixed(self):
        self._owner()
        if self._opened or self._read or self._closed or self._failed:
            raise OptionsSourcesUnavailable()
        self._opened = True
        try:
            for index in range(10):
                self._open(index)
            # Reserve whole allowances before any lseek/read of source bytes.
            if sum(self._ids[i][6] for i in (4, 5, 6)) > 4*_MIB:
                raise OptionsSourcesUnavailable()
            if sum(self._ids[i][6] for i in (8, 9)
                   if self._states[i] == 'owned') > 2*_MIB:
                raise OptionsSourcesUnavailable()
            self._recheck()
            self._acquired = True
        except BaseException as error:
            self._body_failure = _first(self._body_failure, error)
            self._failed = True
            if isinstance(error, OSError):
                raise OptionsSourcesUnavailable() from None
            raise

    def _recheck(self):
        self._owner()
        self._current()
        if self._closed or self._failed:
            raise OptionsSourcesUnavailable()
        for index, descriptor in enumerate(self._fds):
            self._current()
            state = self._states[index]
            if index >= 8 and state == 'absent-observed':
                try:
                    appeared = os.stat(_NAMES[index], dir_fd=self._fds[3], follow_symlinks=False)
                except OSError as error:
                    if error.errno != errno.ENOENT:
                        raise
                    self._absence_errors[index] = error
                else:
                    # Includes a symlink: no follow and no open/replacement.
                    self._named_results[index] = appeared
                    self._current()
                    raise OptionsSourcesUnavailable()
                self._current()
                continue
            if state != 'owned':
                raise OptionsSourcesUnavailable()
            held = os.fstat(descriptor)
            self._held_results[index] = held
            self._current()
            self._check(held, index)
            if _identity(held) != self._ids[index]:
                raise OptionsSourcesUnavailable()
            if index:
                self._current()
                named = os.stat(_NAMES[index], dir_fd=self._fds[_PARENTS[index]],
                                follow_symlinks=False)
                self._named_results[index] = named
                self._current()
                self._check(named, index)
                if _identity(named) != self._ids[index]:
                    raise OptionsSourcesUnavailable()
            self._current()

    def _bytes(self, pass_index, index):
        self._current()
        if index >= 8 and self._states[index] == 'absent-observed':
            return None
        offset = index-4
        cap = _LIMITS[offset]
        os.lseek(self._fds[index], 0, os.SEEK_SET)
        self._current()
        raw = bytearray()
        self._buffers[pass_index][offset] = raw
        while len(raw) <= cap:
            self._current()
            piece = os.read(self._fds[index], min(65536, cap+1-len(raw)))
            self._chunks[pass_index][offset] = piece
            self._current()
            if not piece:
                break
            raw.extend(piece)
        if len(raw) != self._ids[index][6] or not 0 <= len(raw) <= cap:
            raise OptionsSourcesUnavailable()
        value = bytes(raw)
        self._results[pass_index][offset] = value
        return value

    def read_sources(self):
        self._owner()
        if self._closed or self._failed or not self._acquired or self._read:
            raise OptionsSourcesUnavailable()
        self._read = True
        try:
            self._recheck()
            for pass_index in (0, 1):
                for index in range(4, 10):
                    self._results[pass_index][index-4] = self._bytes(pass_index, index)
                self._recheck()
            if self._results[0] != self._results[1]:
                raise OptionsSourcesUnavailable()
            return tuple(self._results[0])
        except BaseException as error:
            self._body_failure = _first(self._body_failure, error)
            self._failed = True
            if isinstance(error, OSError):
                raise OptionsSourcesUnavailable() from None
            raise

    def close(self):
        self._owner()
        self._closed = True
        for index in range(9, -1, -1):
            if self._states[index] != 'owned':
                continue
            self._states[index] = 'close-attempted'
            try:
                os.close(self._fds[index])
            except BaseException as error:
                self._close_errors[index] = error
                self._states[index] = 'uncertain'
                self._close_failure = _first(self._close_failure, error)
            else:
                self._states[index] = 'closed'
        failure = self._close_failure
        if failure is not None and (not isinstance(failure, Exception) or isinstance(failure, MemoryError)):
            raise failure
        if failure is not None or any(state not in ('unused', 'absent-observed', 'closed')
                                      for state in self._states):
            raise OptionsSourcesClosureUncertain() from None
        # No deadline gate on cleanup. Local success is not outside native
        # physical retirement; unknown operations remain the original parent's.

    def close_observations(self):
        self._owner()
        return tuple(self._states)


# No native factory, profile qualification, parser/source selection, bootstrap,
# full11 configuration, installation binding, route, issuer or activation.
