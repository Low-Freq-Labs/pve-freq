"""Fixed reviewed original HTML/static acquisition; uninstalled source only.

Actual original supervisor/installation ownership must precede every native
operation. Private bytes and exact hashes are data, not a source/session/frame
grant. No supplied root, manifest, stream, callback or path is accepted. File
checks cannot qualify ACL/mount/code custody, exclude writers or establish an
active installation. All work here belongs outside every admission gate.
"""
import errno
import hashlib
import math
import os
import stat
import threading
import time


SELECTED_ASSET_REVISION = 'original-guest-workspace-20261024-r50'
# Fixed exact R23 guest-workspace asset DATA; independent policy review required before adoption.
# (parent index, basename, directory, exact size, sha256, MIME, private key)
_NODES = (
    (None, '/', True, None, None, None, None),
    (0, 'usr', True, None, None, None, None),
    (1, 'lib', True, None, None, None, None),
    (2, 'pve-freq', True, None, None, None, None),
    (3, 'cluster-pilot', True, None, None, None, None),
    (4, 'web', True, None, None, None, None),
    (5, 'css', True, None, None, None, None),
    (5, 'js', True, None, None, None, None),
    (7, 'cluster-observation', True, None, None, None, None),
    (5, 'vendor', True, None, None, None, None),
    (9, 'xterm', True, None, None, None, None),
    (5, 'app.html', False, 116105, '93e197abe5d5aea5433278544ace15a3c9fcceac4fc8804e00e2dcc70df438b1', 'text/html', 'app.html'),
    (6, 'app.css', False, 119459, 'e72da094257628338ecbcac0c8ea8a945e59d624173ef4a396d6d2a8e5000b9c', 'text/css', 'css/app.css'),
    (10, 'xterm.min.css', False, 2657, 'b3dee1c4fd6401160a95d726d6532fc72c8e38f2392b66d552a88aa22cb23e12', 'text/css', 'vendor/xterm/xterm.min.css'),
    (10, 'xterm.min.js', False, 289557, 'c396d1fb827e8dbd0df413b1aff16f3cc662c480924c7a1831a2d20b9a2d3098', 'application/javascript', 'vendor/xterm/xterm.min.js'),
    (10, 'addon-fit.min.js', False, 1618, 'c22de0e0e65f0ba77ca6c341c984b5da549ed56c18fcb080b38d201692bfec47', 'application/javascript', 'vendor/xterm/addon-fit.min.js'),
    (10, 'addon-clipboard.min.js', False, 6476, '243df279a2c09c1251b4fc70447200d66dc30e6b28ef33fb85531a3d94eec755', 'application/javascript', 'vendor/xterm/addon-clipboard.min.js'),
    (7, 'router.js', False, 5169, '34dd5a4310089dcd5614e141fe42086585b7a9c72975774db081bfe393582e90', 'application/javascript', 'js/router.js'),
    (7, 'presentation.js', False, 2324, '38236c70a38d16b8579ca91c366a5539a29f2b8c138beb81159de88e4e84d66e', 'application/javascript', 'js/presentation.js'),
    (7, 'quick-ct.js', False, 13411, '24c458c36a654b9e3360889da26dc30ecb85a6aaaa2459b1dc7a859ab0669f67', 'application/javascript', 'js/quick-ct.js'),
    (7, 'app.js', False, 2595491, '74811ac2ccdc0f0303c5f0365ef6748e5e94f446d0aba9c219a8af69a0d6863c', 'application/javascript', 'js/app.js'),
    (8, 'entry-decoder.mjs', False, 5104, '87fbaf72906333a52c5fef4955580bc6ffd1b71dd0fa03795d548659e2b8d37c', 'application/javascript', 'js/cluster-observation/entry-decoder.mjs'),
    (8, 'observation-display.mjs', False, 12968, '1ab978f891c9574bef89b8b30718e0f10a69275d177eefc523f80b3a6705c513', 'application/javascript', 'js/cluster-observation/observation-display.mjs'),
    (8, 'observation-decoder.mjs', False, 8832, 'ace8e2922980242b8de84bb305a36ed3c386e516dc56f47905a74ba2d5cc6b0f', 'application/javascript', 'js/cluster-observation/observation-decoder.mjs'),
)


class PilotAssetsUnavailable(Exception):
    def __init__(self):
        super().__init__('Cluster assets unavailable')


class PilotAssetsClosureUncertain(PilotAssetsUnavailable):
    pass


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _first(first, later):
    if later is None:
        return first
    if (first is None or
            (isinstance(first, Exception) and not isinstance(later, Exception)) or
            (isinstance(first, Exception) and not isinstance(first, MemoryError) and
             isinstance(later, MemoryError))):
        return later
    return first


class FixedPilotAssetAttempt:
    """One original attempt retaining all native files and exact private bytes.

    original_end is original-parent data, not proof of a request reservation.
    The actual issuer must bind this SAME attempt/shortened end/resources to
    its original installation and epoch. Class/type/hash equality cannot issue
    that binding or turn a copied body into an admitted response.
    """
    __slots__ = ('_end', '_thread', '_fds', '_states', '_identities', '_state',
                 '_cleanup', '_payloads', '_asset_errors', '_asset_failure')

    def __init__(self, original_end):
        if type(self) is not FixedPilotAssetAttempt or hasattr(self, '_state'):
            raise PilotAssetsUnavailable()
        if type(original_end) is not float or not math.isfinite(original_end):
            raise PilotAssetsUnavailable()
        # Spend initialization before allocating holders. A partial allocation
        # cannot be retried to replace an existing native duty or its end.
        self._state = 'constructing'
        self._asset_errors = [None] * (len(_NODES) + 2)
        self._asset_failure = None
        self._end = original_end
        self._thread = threading.current_thread()
        self._fds = [None] * len(_NODES)
        self._states = ['unused'] * len(_NODES)
        self._identities = [None] * len(_NODES)
        self._state = 'new'
        self._cleanup = 'not-attempted'
        self._payloads = None

    def _owner(self):
        if threading.current_thread() is not self._thread:
            raise PilotAssetsUnavailable()

    def _current(self):
        self._owner()
        if self._state not in ('acquiring', 'retained') or not time.monotonic() < self._end:
            raise PilotAssetsUnavailable()

    def _check(self, index, info):
        _, _, directory, size, _, _, _ = _NODES[index]
        kind = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if (not kind or info.st_uid != 0 or info.st_mode & 0o022 or
                (not directory and (info.st_nlink != 1 or info.st_size != size))):
            raise PilotAssetsUnavailable()

    def _open_all(self):
        for index, (parent, name, directory, _, _, _, _) in enumerate(_NODES):
            self._current()
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
            flags |= os.O_DIRECTORY if directory else os.O_NONBLOCK
            self._states[index] = 'acquire-pending'
            try:
                fd = os.open(name, flags) if parent is None else os.open(
                    name, flags, dir_fd=self._fds[parent])
            except OSError as error:
                if error.errno == errno.ENOENT:
                    self._states[index] = 'known-absent'
                raise
            # Store the returned original handle BEFORE clock/stat or another
            # native call. Lost return remains covered by preowned worker.
            self._fds[index] = fd
            self._states[index] = 'owned'
            self._current()
            info = os.fstat(fd)
            self._check(index, info)
            self._identities[index] = _identity(info)
            self._current()

    def _recheck(self):
        self._current()
        for index, (parent, name, _, _, _, _, _) in enumerate(_NODES):
            if self._states[index] != 'owned':
                raise PilotAssetsUnavailable()
            info = os.fstat(self._fds[index])
            self._check(index, info)
            if _identity(info) != self._identities[index]:
                raise PilotAssetsUnavailable()
            self._current()
            if parent is not None:
                named = os.stat(name, dir_fd=self._fds[parent], follow_symlinks=False)
                self._check(index, named)
                if _identity(named) != self._identities[index]:
                    raise PilotAssetsUnavailable()
                self._current()

    def _read_file(self, index):
        expected = _NODES[index][3]
        chunks, count = [], 0
        self._current()
        while count <= expected:
            self._current()
            block = os.read(self._fds[index], min(16384, expected + 1 - count))
            self._current()
            if not block:
                break
            count += len(block)
            chunks.append(block)
        if count != expected:
            raise PilotAssetsUnavailable()
        raw = b''.join(chunks)
        if hashlib.sha256(raw).hexdigest() != _NODES[index][4]:
            raise PilotAssetsUnavailable()
        self._current()
        return raw

    def acquire(self):
        self._owner()
        if self._state != 'new':
            raise PilotAssetsUnavailable()
        self._state = 'acquiring'
        transferred = False
        first = None
        try:
            self._open_all()  # All24 nodes/metadata precede any asset bytes.
            self._recheck()
            payloads = []
            for index, node in enumerate(_NODES):
                if not node[2]:
                    payloads.append((node[6], node[5], self._read_file(index)))
            self._recheck()
            self._payloads = tuple(payloads)
            self._state = 'retained'
            self._current()
            transferred = True
            return self
        except BaseException as error:
            self._asset_errors[0] = error
            first = self._asset_failure = _first(self._asset_failure, error)
            self._state = 'failed'
        finally:
            if not transferred:
                try:
                    self.retire()
                except BaseException as cleanup:
                    self._asset_errors[-1] = cleanup
                    first = _first(first, cleanup)
        first = self._asset_failure = _first(self._asset_failure, first)
        if first is not None and (not isinstance(first, Exception) or isinstance(first, MemoryError)):
            raise first
        raise PilotAssetsUnavailable() from None

    def private_payload(self, fixed_asset_key):
        # Preparation only, outside admission locks. Returned bytes/MIME are
        # data. Actual original owner must retain the body/frame/request and
        # revalidate currentness in its final transaction before any disclosure.
        self._current()
        if self._state != 'retained' or type(fixed_asset_key) is not str:
            raise PilotAssetsUnavailable()
        for key, mime, raw in self._payloads:
            if key == fixed_asset_key:
                return mime, raw
        raise PilotAssetsUnavailable()

    def retire(self):
        self._owner()
        self._state = 'retired'
        self._payloads = None
        if self._cleanup == 'not-attempted':
            self._cleanup = 'uncertain'
            first = None
            for index in range(len(_NODES) - 1, -1, -1):
                if self._states[index] == 'owned':
                    self._states[index] = 'close-attempted'
                    try:
                        os.close(self._fds[index])
                    except BaseException as error:
                        self._asset_errors[index + 1] = error
                        self._states[index] = 'uncertain'
                        first = _first(first, error)
                    else:
                        self._states[index] = 'closed'
            unsettled = any(s in ('acquire-pending', 'close-attempted', 'uncertain')
                            for s in self._states)
            self._asset_failure = _first(self._asset_failure, first)
            if first is not None and (not isinstance(first, Exception) or isinstance(first, MemoryError)):
                raise first
            if first is not None or unsettled:
                raise PilotAssetsClosureUncertain() from None
            self._cleanup = 'locally-settled'
        if self._cleanup != 'locally-settled':
            raise PilotAssetsClosureUncertain()

    def cleanup_observations(self):
        self._owner()
        return self._state, self._cleanup, tuple(self._states)


# No installation factory, listener, file mutation, credential or route dispatch.
