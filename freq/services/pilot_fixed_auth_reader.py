"""Fixed native authentication input acquisition; SOURCE WORK IN PROGRESS.

This reads existing configured users and the existing encrypted Vault. It does
not bootstrap, migrate, initialize, repair or write them. Returned bytes are
private input DATA, never installation/current-user/session authority.

The original supervised process must retain this object BEFORE open_fixed.
Blocked syscalls and successful acquisitions whose return is lost require that
parent's physical retirement. Metadata and two equal reads do not establish
writer exclusion, an atomic snapshot, code identity, ACL/mount enforcement or a
hard deadline. No credential access is selected by publishing this source.
"""
import math
import os
import stat
import threading
import time


_MIB = 1048576
# Every parent is an original held descriptor. No cwd, environment, request,
# configuration-selected path, legacy loader or alternate location is used.
_PARENTS = (None, 0, 1, 2, 3, 3, 3, 2, 7, 8, 0, 10)
_NAMES = ('/', 'opt', 'pve-freq', 'conf', 'freq.toml', 'users.conf',
          'roles.conf', 'data', 'vault', 'freq-vault.enc', 'etc', 'machine-id')
_DIRECTORIES = frozenset((0, 1, 2, 3, 7, 8, 10))
_OPTIONAL = frozenset((5, 6))
_FILES = (4, 5, 6, 9, 11)


class PilotAuthInputUnavailable(Exception):
    def __init__(self):
        super().__init__('Pilot authentication inputs unavailable')


class PilotAuthInputClosureUncertain(Exception):
    def __init__(self):
        super().__init__('Pilot authentication input cleanup unresolved')


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class FixedOriginalAuthReader:
    """One original thread, one acquisition, two whole bounded input reads.

    UIDs/end are retained parent data and shape filters, not proof of original
    principal/deadline capture. The actual startup owner must bind this reader
    to its source/credential writer fence and preserve that binding through
    password verification and final ordered auth/reference/HTTP admission.

    Fixed profile proposal: root owns /opt/pve-freq and its data directory;
    source_uid owns conf and its three inputs; credential_uid owns private
    data/vault and its existing 0600 ciphertext. These distinct identities
    require actual infrastructure review/selection, not an automatic chmod,
    chown, new account, copied manifest or Boolean qualification flag.
    """
    __slots__ = ('_source_uid', '_credential_uid', '_end', '_thread', '_fds',
                 '_states', '_ids', '_started', '_read', '_closed')

    def __init__(self, source_uid, credential_uid, original_deadline):
        if (type(source_uid) is not int or type(credential_uid) is not int or
                not 1 <= source_uid <= 4294967294 or
                not 1 <= credential_uid <= 4294967294 or
                source_uid == credential_uid or
                type(original_deadline) is not float or
                not math.isfinite(original_deadline)):
            raise PilotAuthInputUnavailable()
        self._source_uid = source_uid
        self._credential_uid = credential_uid
        self._end = original_deadline
        self._thread = threading.current_thread()
        self._fds = [None] * 12
        self._states = ['unused'] * 12
        self._ids = [None] * 12
        self._started = self._read = self._closed = False

    def _owner(self):
        if threading.current_thread() is not self._thread:
            raise PilotAuthInputUnavailable()

    def _current(self):
        if not time.monotonic() < self._end:
            raise PilotAuthInputUnavailable()

    def _check(self, info, index):
        directory = index in _DIRECTORIES
        uid = (self._source_uid if index in (3, 4, 5, 6) else
               self._credential_uid if index in (8, 9) else 0)
        if (info.st_uid != uid or info.st_mode & 0o022 or
                (not stat.S_ISDIR(info.st_mode) if directory
                 else not stat.S_ISREG(info.st_mode))):
            raise PilotAuthInputUnavailable()
        if index == 8 and stat.S_IMODE(info.st_mode) != 0o700:
            raise PilotAuthInputUnavailable()
        if not directory:
            limit = 33 if index == 11 else _MIB
            minimum = 1 if index in (4, 9) else 0
            if info.st_nlink != 1 or not minimum <= info.st_size <= limit:
                raise PilotAuthInputUnavailable()
            if index == 9 and stat.S_IMODE(info.st_mode) != 0o600:
                raise PilotAuthInputUnavailable()
            if index == 11 and info.st_size not in (32, 33):
                raise PilotAuthInputUnavailable()

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
                raise PilotAuthInputUnavailable() from None
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
            raise PilotAuthInputUnavailable()
        self._started = True
        for index in range(12):
            self._open(index)
        # All five metadata/absence checks precede every secret/source byte.
        total = sum(self._ids[i][6] for i in _FILES
                    if self._states[i] == 'owned')
        if total > 4 * _MIB + 33:
            raise PilotAuthInputUnavailable()
        self._recheck()

    def _recheck(self):
        self._current()
        for index in range(12):
            state = self._states[index]
            if state == 'absent' and index in _OPTIONAL:
                try:
                    os.stat(_NAMES[index], dir_fd=self._fds[_PARENTS[index]],
                            follow_symlinks=False)
                except FileNotFoundError:
                    self._current()
                    continue
                raise PilotAuthInputUnavailable()
            if state != 'owned':
                raise PilotAuthInputUnavailable()
            self._current()
            held = os.fstat(self._fds[index])
            self._check(held, index)
            if _identity(held) != self._ids[index]:
                raise PilotAuthInputUnavailable()
            if index:
                self._current()
                named = os.stat(_NAMES[index], dir_fd=self._fds[_PARENTS[index]],
                                follow_symlinks=False)
                self._check(named, index)
                if _identity(named) != self._ids[index]:
                    raise PilotAuthInputUnavailable()
            self._current()

    def _bytes(self, index):
        if self._states[index] == 'absent' and index in _OPTIONAL:
            return None
        self._current()
        os.lseek(self._fds[index], 0, os.SEEK_SET)
        maximum = 33 if index == 11 else _MIB
        result = bytearray()
        while True:
            self._current()
            # One overflow sentinel; extend only after testing remaining cap.
            chunk = os.read(self._fds[index], min(16384, maximum - len(result) + 1))
            self._current()
            if not chunk:
                break
            if len(chunk) > maximum - len(result):
                raise PilotAuthInputUnavailable()
            result.extend(chunk)
        if len(result) != self._ids[index][6]:
            raise PilotAuthInputUnavailable()
        return bytes(result)

    def read_inputs(self):
        self._owner()
        if not self._started or self._read or self._closed:
            raise PilotAuthInputUnavailable()
        self._read = True
        self._recheck()
        first = tuple(self._bytes(i) for i in _FILES)
        self._recheck()
        second = tuple(self._bytes(i) for i in _FILES)
        self._recheck()
        if first != second:
            raise PilotAuthInputUnavailable()
        # Exact order: freq.toml, optional users.conf, optional roles.conf,
        # existing data/vault/freq-vault.enc, /etc/machine-id. Private data only.
        return first

    def close(self):
        self._owner()
        self._closed = True
        control = None
        for index in range(11, -1, -1):
            if self._states[index] != 'owned':
                continue
            self._states[index] = 'close-attempted'
            try:
                os.close(self._fds[index])
            except BaseException as error:
                self._states[index] = 'uncertain'
                if control is None and not isinstance(error, Exception):
                    control = error
            else:
                self._states[index] = 'closed'
        if control is not None:
            raise control
        if any(state not in ('unused', 'absent', 'closed') for state in self._states):
            raise PilotAuthInputClosureUncertain()

    def cleanup_observations(self):
        self._owner()
        return tuple(self._states)


# No entrypoint, native launch, path override, source issuer or positive factory.
