"""Uninstalled retained optional-options acquisition; never a source issuer.

The outside original parent must retain this exact attempt before acquire and
owns source/code/principal/namespace/all-writer/purpose/generation/physical end
and retirement. This class neither supplies nor authenticates that parent.
Fixed local reader objects, equal bytes and configured/private DATA prove no
native authority. No caller reader, callback, lock, path or native observation.
"""
import math
import threading
import time

from freq.services.pilot_fixed_options_source_reader import FixedOptionsSourceReader
from freq.services.pilot_fixed_startup_identity import FixedStartupIdentityReader
from freq.services.pilot_startup_inputs import decode_fixed_startup_inputs
from freq.services.pilot_configured_cohort import (
    PilotConfiguredData, prepare_configured_cohort_data,
)
from freq.services.vm_options_selected_data import (
    SelectedOptionsPreparedFieldsData, prepare_selected_options_fields_data,
)


class OptionsAcquisitionUnavailable(Exception):
    def __init__(self):
        super().__init__('VM options acquisition unavailable')


class OptionsAcquisitionClosureUncertain(Exception):
    def __init__(self):
        super().__init__('VM options acquisition cleanup unresolved')


def _first(first, later):
    if later is None:
        return first
    if (first is None or
            (isinstance(first, Exception) and not isinstance(later, Exception)) or
            (isinstance(first, Exception) and not isinstance(first, MemoryError) and
             isinstance(later, MemoryError))):
        return later
    return first


class OriginalOptionsInputAttempt:
    """Same retained six-source/identity readers; private ten fields only.

Construction allocates Python holders and reader objects, with no source IO.
An unknown constructor return cannot license retrying an acquiring operation.
The original parent retains this object before acquire. Retirement revokes
private getters but keeps reader/buffer/result/error references: local cleanup
success does not prove physical retirement or authorize releasing unknown duties.
"""
    __slots__ = ('_state', '_thread', '_end', '_revision', '_sources', '_identity',
                 '_source_bytes', '_identity_bytes', '_startup_data',
                 '_configured', '_prepared', '_errors', '_failure',
                 '_cleanup_state', '_cleanup_failure', '_cleanup_children')

    def __init__(self, source_uid, original_deadline, original_revision):
        if type(self) is not OriginalOptionsInputAttempt or hasattr(self, '_state'):
            raise OptionsAcquisitionUnavailable()
        self._state = 'constructing'
        self._errors, self._failure = [None]*4, None
        self._cleanup_state, self._cleanup_failure = 'not-attempted', None
        self._sources = self._identity = None
        self._cleanup_children = [None, None]
        self._source_bytes = self._identity_bytes = self._startup_data = None
        self._configured = self._prepared = None
        self._thread = threading.current_thread()
        if (type(source_uid) is not int or not 1 <= source_uid <= 4294967294 or
                type(original_deadline) is not float or not math.isfinite(original_deadline) or
                type(original_revision) is not str or not 0 < len(original_revision) <= 512):
            raise OptionsAcquisitionUnavailable()
        self._end, self._revision = original_deadline, original_revision
        # Retain each known pure holder before initializing it. Only a known
        # successful initializer return registers a reader for cleanup.
        self._sources = object.__new__(FixedOptionsSourceReader)
        FixedOptionsSourceReader.__init__(self._sources, source_uid, original_deadline)
        self._cleanup_children[0] = self._sources
        self._identity = object.__new__(FixedStartupIdentityReader)
        FixedStartupIdentityReader.__init__(self._identity, source_uid, original_deadline)
        self._cleanup_children[1] = self._identity
        self._state = 'new'

    def __init_subclass__(cls, **kwargs):
        raise TypeError('original options attempt cannot be subclassed')

    def __copy__(self):
        raise TypeError('original options attempt cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('original options attempt cannot be copied')

    def __reduce_ex__(self, protocol):
        raise TypeError('original options attempt cannot be serialized')

    def _owner(self):
        if threading.current_thread() is not self._thread:
            raise OptionsAcquisitionUnavailable()

    def _current(self):
        self._owner()
        if (self._state not in ('acquiring', 'retained') or
                not time.monotonic() < self._end):
            raise OptionsAcquisitionUnavailable()
        # Real native diagnostics outside every admission gate; never a writer
        # fence, continuous absence proof, namespace/principal or physical lease.
        self._sources._recheck()
        self._identity._recheck()
        if not time.monotonic() < self._end:
            raise OptionsAcquisitionUnavailable()

    def acquire(self):
        self._owner()
        if self._state != 'new':
            raise OptionsAcquisitionUnavailable()
        self._state = 'acquiring'
        try:
            if not time.monotonic() < self._end:
                raise OptionsAcquisitionUnavailable()
            self._sources.open_fixed()
            self._identity.open_fixed()
            self._current()
            self._source_bytes = self._sources.read_sources()
            self._current()
            self._identity_bytes = self._identity.read_inputs()
            self._current()
            if (type(self._source_bytes) is not tuple or len(self._source_bytes) != 6 or
                    type(self._identity_bytes) is not tuple or len(self._identity_bytes) != 3):
                raise OptionsAcquisitionUnavailable()
            # The existing startup decoder enforces exact four-byte caps and
            # complete duplicated freq agreement; no winning-source selection.
            self._startup_data = decode_fixed_startup_inputs(self._source_bytes[:4],
                                                            *self._identity_bytes)
            self._current()
            self._configured = prepare_configured_cohort_data(self._startup_data,
                                                              self._revision)
            self._current()
            if type(self._configured) is not PilotConfiguredData:
                raise OptionsAcquisitionUnavailable()
            self._prepared = prepare_selected_options_fields_data(
                self._source_bytes[0], self._source_bytes[4],
                self._source_bytes[2], self._source_bytes[5], self._configured)
            self._current()
            if type(self._prepared) is not SelectedOptionsPreparedFieldsData:
                raise OptionsAcquisitionUnavailable()
            self._state = 'retained'
            return self
        except BaseException as error:
            failure = error
        self._fail_and_retire(failure)

    def _fail_and_retire(self, error):
        self._errors[0] = error
        self._failure = _first(self._failure, error)
        self._state = 'failed'
        try:
            self.retire()
        except BaseException as surface:
            # Surface may be the retained body control/memory selected over a
            # weaker cleanup failure. Actual child errors have separate slots.
            self._errors[3] = surface
            self._failure = _first(self._failure, surface)
        failure = self._failure
        if failure is not None and (not isinstance(failure, Exception) or isinstance(failure, MemoryError)):
            raise failure
        raise OptionsAcquisitionUnavailable() from None

    def private_prepared_data(self):
        self._owner()
        if self._state != 'retained':
            raise OptionsAcquisitionUnavailable()
        failure = None
        try:
            self._current()
            if type(self._prepared) is not SelectedOptionsPreparedFieldsData:
                raise OptionsAcquisitionUnavailable()
        except BaseException as error:
            failure = error
        if failure is not None:
            self._fail_and_retire(failure)
        return self._prepared

    def private_configured_data(self):
        self._owner()
        if self._state != 'retained':
            raise OptionsAcquisitionUnavailable()
        failure = None
        try:
            self._current()
            if type(self._configured) is not PilotConfiguredData:
                raise OptionsAcquisitionUnavailable()
        except BaseException as error:
            failure = error
        if failure is not None:
            self._fail_and_retire(failure)
        return self._configured

    def retire(self):
        self._owner()
        self._state = 'retired'
        if self._cleanup_state == 'not-attempted':
            self._cleanup_state = 'uncertain'
            # Each same original reader is attempted once, including after
            # body/control/MemoryError. Child close retains its actual failures.
            for index, child in enumerate(self._cleanup_children, 1):
                if child is None:
                    continue  # Pure constructor never acquired an FD.
                try:
                    child.close()
                except BaseException as error:
                    self._errors[index] = error
                    self._cleanup_failure = _first(self._cleanup_failure, error)
                    self._failure = _first(self._failure, error)
            if self._cleanup_failure is None:
                self._cleanup_state = 'locally-settled'
        failure = self._failure
        if failure is not None and (not isinstance(failure, Exception) or isinstance(failure, MemoryError)):
            raise failure
        if self._cleanup_state != 'locally-settled':
            raise OptionsAcquisitionClosureUncertain() from None
        # Retain all references. This local label is neither physical closure
        # nor permission to clear the original parent's unknown native ledger.

    def cleanup_observations(self):
        self._owner()
        return (self._state, self._cleanup_state,
                None if self._sources is None else self._sources.close_observations(),
                None if self._identity is None else self._identity.cleanup_observations())


# No original parent/factory/writer/issuer installation, key/bootstrap/full11,
# native-currentness admission, public response, route, listener or activation.
