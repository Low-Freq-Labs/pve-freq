"""Process-local source invalidation; never installation or read authority.

Only participating writers are covered. Other application writers, processes,
administrators, provider writers and system trust changes remain separate work.
No view is issued here. An epoch match is only a necessary refusal filter.
"""
import threading


_gate = threading.RLock()
_table_gate = threading.Lock()
_epoch = object()
_writers = {}
_readers = {}
_MAX_WRITERS = 16
_reads_retired = False  # One-way refusal in this original process only.


class SourceWriteUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Source update unavailable')


def _first(first, later):
    if first is None or issubclass(type(first), Exception) and (
            not issubclass(type(later), Exception)
            or not issubclass(type(first), MemoryError)
            and issubclass(type(later), MemoryError)):
        return later
    return first


class source_write:
    """Invalidate before a participating effect, with no waiting/retry queue.

    Retain this exact context before entering it. Unknown gate acquisition or
    release remains in the bounded original table; never guess unlock/refund.
    The source gate precedes Vault/auth/view gates. No caller supplies a lock,
    epoch, invalidation callback, installation or qualification flag.
    """
    __slots__ = ('thread', 'stage', 'body_failure', 'release_failure',
                 'validation_failure', 'failure', '_used', '_retained',
                 '_initialization_spent')

    def __init__(self):
        if type(self) is not source_write or hasattr(self, '_initialization_spent'):
            raise SourceWriteUnavailable()
        # Spend before fallible thread storage; never replace retained duties.
        self._initialization_spent = True
        self.thread = threading.current_thread()
        self.stage = 'unused'
        self.body_failure = self.release_failure = self.failure = None
        self.validation_failure = None
        self._used = self._retained = False

    def __enter__(self):
        global _epoch
        if self._used or threading.current_thread() is not self.thread:
            raise SourceWriteUnavailable()
        self._used = True
        with _table_gate:
            if _readers or len(_writers) >= _MAX_WRITERS or any(
                    item.stage != 'invalidated' for item in _writers.values()):
                raise SourceWriteUnavailable()
            _writers[id(self)] = self
            self._retained = True
        self.stage = 'acquire-pending'
        try:
            acquired = _gate.acquire(blocking=False)
        except BaseException as error:
            self.failure = error
            raise
        if not acquired:
            self.stage = 'not-acquired'
            self._forget()
            raise SourceWriteUnavailable()
        self.stage = 'owned'
        try:
            # Allocate before publishing the new original generation. A failed
            # allocation never enters the writer body or restores an old epoch.
            replacement = object()
            _epoch = replacement
            self.stage = 'invalidated'
        except BaseException as error:
            self.body_failure = self.failure = error
            self._release()
            raise self.failure from None
        return self

    def _forget(self):
        with _table_gate:
            if _writers.get(id(self)) is self:
                del _writers[id(self)]
                self._retained = False

    def _release(self):
        self.stage = 'release-pending'
        try:
            _gate.release()
        except BaseException as error:
            self.release_failure = error
            self.failure = _first(self.failure, error)
            # Even an ordinary unknown release keeps original capacity.
        else:
            self.stage = 'returned'
            try:
                self._forget()
            except BaseException as error:
                self.failure = _first(self.failure, error)

    def __exit__(self, kind, error, traceback):
        # Keep the received body before exit validation can itself fail. The
        # first body and first validation evidence remain independently held.
        if error is not None:
            if self.body_failure is None:
                self.body_failure = error
            self.failure = _first(self.failure, error)
        try:
            if (threading.current_thread() is not self.thread
                    or self.stage != 'invalidated'):
                raise SourceWriteUnavailable()
        except BaseException as validation_error:
            # Ownership/stage was not validated. Keep the original capacity and
            # do not probe release/forget or infer a successful unlock/refund.
            self.stage = 'exit-validation-failed'
            if self.validation_failure is None:
                self.validation_failure = validation_error
            first = self.failure
            for later in (self.validation_failure, validation_error):
                if first is not None and (
                        not issubclass(type(first), Exception)
                        or issubclass(type(first), MemoryError)):
                    first = _first(first, later)
                else:
                    # Preserve original later-validation replacement when both
                    # outcomes are ordinary; protected winners remain first.
                    first = later
            self.failure = first
            raise first from None
        self._release()
        if self.failure is not None:
            raise self.failure from None
        return False


class SourceReadUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Read source unavailable')


class source_read:
    """Retain a nonqueued source critical section; epoch is a negative filter.

    This issues no installation, source, credential, view or target authority.
    Keep original source reads/auth/view checks inside this lexical section;
    provider and HTTP IO belong outside it. A participating writer cannot enter
    while a reader owns or has an uncertain source duty, even on the same thread.
    """
    __slots__ = ('thread', 'stage', 'epoch', 'body_failure', 'release_failure',
                 'forget_failure', 'failure', '_used', '_retained',
                 'rejected', 'entry_failure', '_initialization_spent',
                 'validation_failure')

    def __init__(self):
        if type(self) is not source_read or hasattr(self, '_initialization_spent'):
            raise SourceReadUnavailable()
        # Spend before fallible thread storage; never replace retained duties.
        self._initialization_spent = True
        self.thread = threading.current_thread()
        self.stage = 'unused'
        self.epoch = None
        self.body_failure = self.release_failure = self.forget_failure = None
        self.failure = self.entry_failure = None
        self.rejected = False
        self._used = self._retained = False
        self.validation_failure = None

    def _reject(self):
        # Logical rejection is irreversible and separate from any already
        # owned/uncertain gate and original raw body/release/forget errors.
        self.rejected = True
        if self.entry_failure is None:
            self.entry_failure = SourceReadUnavailable()
        raise self.entry_failure from None

    def __enter__(self):
        if self._used or self.rejected or threading.current_thread() is not self.thread:
            self._reject()
        self._used = True
        with _table_gate:
            if _reads_retired or _writers or _readers:
                raise SourceReadUnavailable()
            _readers[id(self)] = self
            self._retained = True
        self.stage = 'acquire-pending'
        try:
            acquired = _gate.acquire(blocking=False)
        except BaseException as failure:
            self.failure = failure
            raise
        if not acquired:
            self.stage = 'not-acquired'
            self._forget()
            raise SourceReadUnavailable()
        self.stage = 'owned'
        try:
            self.epoch = _epoch
            self.stage = 'captured'
        except BaseException as failure:
            self.body_failure = failure
            self._release()
            raise self.failure from None
        return self

    def _forget(self):
        with _table_gate:
            if _readers.get(id(self)) is self:
                del _readers[id(self)]
                self._retained = False

    def _release(self):
        self.stage = 'release-pending'
        try:
            _gate.release()
        except BaseException as failure:
            self.release_failure = failure
        else:
            self.stage = 'returned'
            try:
                self._forget()
            except BaseException as failure:
                self.forget_failure = failure
        # Independent release/forget above precede error classification.
        first = self.body_failure
        for later in (self.release_failure, self.forget_failure):
            if later is not None:
                first = _first(first, later)
        self.failure = first

    def same_epoch(self, previous):
        """Necessary refusal filter inside this owned gate, never a grant."""
        return (not _reads_retired and not self.rejected and self.stage == 'captured'
                and threading.current_thread() is self.thread
                and self._retained and _readers.get(id(self)) is self
                and type(previous) is source_read
                and not previous.rejected
                and previous._used and not previous._retained
                and previous.stage == 'returned' and previous.failure is None
                and self.epoch is _epoch and previous.epoch is _epoch)

    def __exit__(self, kind, failure, traceback):
        # Retain the received body before thread/stage lookup or rejection can
        # fail. First body and first validation evidence have separate slots.
        if failure is not None:
            if self.body_failure is None:
                self.body_failure = failure
            self.failure = _first(self.failure, failure)
        try:
            if (threading.current_thread() is not self.thread
                    or self.stage != 'captured'):
                self._reject()
        except BaseException as validation_error:
            # Unknown/invalid validation must never release or forget a duty.
            # Mark rejection before any further error selection can fail.
            self.rejected = True
            self.stage = 'exit-validation-failed'
            if self.validation_failure is None:
                self.validation_failure = validation_error
            first = self.failure
            for later in (self.validation_failure, validation_error):
                if first is not None and (
                        not issubclass(type(first), Exception)
                        or issubclass(type(first), MemoryError)):
                    first = _first(first, later)
                else:
                    # Preserve original later-validation replacement for two
                    # ordinary outcomes; keep the first protected winner.
                    first = later
            self.failure = first
            raise first from None
        self._release()
        if self.failure is not None:
            raise self.failure from None
        return False


def retire_process_reads():
    """Permanently refuse this parent's reads before a mutating child launch.

    Original source_write refuses active/uncertain readers and invalidates
    before setting the one-way fence. Unknown acquire/release stays in its
    original table. Scheduler success/failure never clears this fence, and no
    other process, new runtime or child closure is qualified by it.
    """
    global _reads_retired
    with source_write():
        _reads_retired = True
