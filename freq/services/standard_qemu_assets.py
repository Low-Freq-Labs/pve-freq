"""Acquire one complete fixed read-only frontend cohort from the original package.

No supplied filesystem root, manifest, callback, native reader or read grant.
Only a complete byte-exact cohort can become the process-local immutable cache.
The original HTTP serving join remains a separate caller obligation.
"""
import hashlib
import importlib.resources
import threading

from freq.services import standard_qemu_asset_policy as _policy


class AssetUnavailable(Exception):
    """The fixed frontend cannot currently be served coherently."""


class _Attempt:
    __slots__ = ('stage', 'streams', 'close_stages', 'read_stages', 'bodies',
                 'failure', 'close_failures', 'release_failure')

    def __init__(self):
        self.stage = 'retained'
        self.streams = [None] * 24
        self.close_stages = ['unused'] * 24
        self.read_stages = ['unused'] * 24
        self.bodies = [None] * 24
        self.failure = self.release_failure = None
        self.close_failures = [None] * 24


_LOAD_GATE = threading.Lock()
_ATTEMPT = None
_COHORT = None
_CONSTRUCTION_PENDING = object()
_LOAD_FAILURES = [None, None]  # original first load/body and independent release


def _first(first, later):
    if later is None:
        return first
    if first is None or issubclass(type(first), Exception) and (
            not issubclass(type(later), Exception)
            or not issubclass(type(first), MemoryError)
            and issubclass(type(later), MemoryError)):
        return later
    return first


def _read_one(attempt, root, index, key, size, digest):
    # Rooted holders precede open/read. A lost open/close result is never
    # replaced with a fabricated acknowledgement or a second attempt.
    attempt.close_stages[index] = 'open-pending'
    stream = root.joinpath(key).open('rb')
    attempt.streams[index] = stream
    attempt.close_stages[index] = 'owned'
    try:
        attempt.read_stages[index] = 'pending'
        body = stream.read(size + 1)
        attempt.read_stages[index] = 'returned'
        if (type(body) is not bytes or len(body) != size
                or hashlib.sha256(body).hexdigest() != digest):
            raise AssetUnavailable('Fixed frontend unavailable')
        attempt.bodies[index] = body
    except BaseException as failure:
        attempt.failure = failure
    attempt.close_stages[index] = 'close-pending'
    try:
        stream.close()
    except BaseException as failure:
        attempt.close_failures[index] = failure
        attempt.close_stages[index] = 'close-uncertain'
    else:
        attempt.close_stages[index] = 'closed'
    # Independent close above precedes classification of either raw error.
    attempt.failure = _first(attempt.failure, attempt.close_failures[index])
    if attempt.failure is not None:
        raise attempt.failure from None


def _load_cohort():
    global _ATTEMPT, _COHORT
    if _COHORT is not None:
        return _COHORT
    if _ATTEMPT is not None:
        raise AssetUnavailable('Fixed frontend unavailable')
    if not _LOAD_GATE.acquire(blocking=False):
        raise AssetUnavailable('Fixed frontend unavailable')
    attempt = cohort = first = None
    started = False
    try:
        if _COHORT is not None:
            cohort = _COHORT
        elif _ATTEMPT is not None:
            # Even an ordinary first failure consumes this process's single
            # acquisition. Restart after repairing the package; no fallback.
            raise AssetUnavailable('Fixed frontend unavailable')
        else:
            # Consume before fallible holder allocation. The static marker and
            # raw-error pair retain a failed construction without a retry.
            started = True
            _ATTEMPT = _CONSTRUCTION_PENDING
            attempt = _Attempt()
            _ATTEMPT = attempt
            root = importlib.resources.files('freq.data.web')
            if (len(_policy._ASSETS) != 24
                    or sum(row[3] for row in _policy._ASSETS) > 4 * 1024 * 1024):
                raise AssetUnavailable('Fixed frontend unavailable')
            for index, (_, key, _, size, digest) in enumerate(_policy._ASSETS):
                _read_one(attempt, root, index, key, size, digest)
            cohort = tuple(attempt.bodies)
            attempt.stage = 'validated'
    except BaseException as failure:
        first = failure
        if started:
            _LOAD_FAILURES[0] = failure
        if attempt is not None:
            attempt.failure = failure
            attempt.stage = 'failed-retained'
    release_failure = None
    try:
        _LOAD_GATE.release()
    except BaseException as failure:
        release_failure = failure
        if started:
            _LOAD_FAILURES[1] = failure
        if attempt is not None:
            attempt.release_failure = failure
            attempt.stage = 'gate-release-uncertain'
    first = _first(first, release_failure)
    if first is not None:
        if attempt is not None:
            attempt.failure = first
        if not issubclass(type(first), Exception) or issubclass(type(first), MemoryError):
            raise first from None
        raise AssetUnavailable('Fixed frontend unavailable') from None
    # Publication occurs only after all twenty-one exact reads/closes AND known
    # gate release. The cached bytes keep one fixed revision across requests.
    _COHORT = cohort
    return cohort


def get_asset(method, raw_target):
    """Return fixed MIME/bytes/SHA DATA, or None for an unmapped raw target."""
    selected = _policy.select_asset(method, raw_target)
    if selected is None:
        return None
    key, mime, _, digest = selected
    cohort = _load_cohort()
    for index, row in enumerate(_policy._ASSETS):
        if row[1] == key:
            return mime, cohort[index], digest
    raise AssetUnavailable('Fixed frontend unavailable')
