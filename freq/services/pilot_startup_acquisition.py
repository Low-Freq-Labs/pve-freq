"""Original fixed startup acquisition composition; uninstalled native source.

The actual outer original owner must retain this SAME attempt before acquire.
Its real source/principal/code/writer/resource lifetime remains mandatory.
No supplied bytes, reader, parser, callback, lock or positive native owner is
accepted. Private configured DATA is not a factory or installation issuer.
"""
import threading
import time

from freq.services.pilot_fixed_startup_reader import FixedStartupSourceReader
from freq.services.pilot_fixed_startup_identity import FixedStartupIdentityReader
from freq.services.pilot_startup_inputs import decode_fixed_startup_inputs
from freq.services.pilot_configured_cohort import (
    PilotConfiguredData, prepare_configured_cohort_data,
)
from freq.services.pilot_fleet_targets_data import (
    ConfiguredFleetTargetsData, FleetTargetDataUnavailable,
    decode_fleet_target_bytes,
)


class PilotStartupAcquisitionUnavailable(Exception):
    def __init__(self):
        super().__init__('Pilot startup acquisition unavailable')


class PilotStartupAcquisitionClosureUncertain(Exception):
    pass


def _first(first, later):
    if first is None or (isinstance(first, Exception) and (
            not isinstance(later, Exception) or
            not isinstance(first, MemoryError) and isinstance(later, MemoryError))):
        return later
    return first


class OriginalStartupInputAttempt:
    """Same actual readers, inherited end and private original consumer DATA.

    This does not select a Vault, password hash or node token credential file.
    Configuration bytes can contain sensitive values and remain private; no
    bytes, parser errors, file names or data are logged or exported here.
    Actual native-confirmed absent configured users/roles stay absent, without
    a default administrator, store creation, repair or legacy fallback.
    """
    __slots__ = ('_sources', '_identity', '_thread', '_end', '_revision',
                 '_state', '_cleanup', '_data', '_fleet_targets_data',
                 '_acquisition_errors', '_acquisition_failure')

    def __init__(self, source_uid, original_deadline, original_revision):
        # Permanent one-shot marker before validation or holder construction.
        # Reinitialization must never replace readers retained by an earlier
        # acquisition, reopen a retired attempt or renew its original deadline.
        if type(self) is not OriginalStartupInputAttempt or hasattr(self, '_state'):
            raise PilotStartupAcquisitionUnavailable()
        self._state = 'constructing'
        # Pure fixed storage before any reader acquisition; never reset on retry.
        self._acquisition_errors = [None] * 4
        self._acquisition_failure = None
        if (type(original_revision) is not str or
                not 0 < len(original_revision) <= 512):
            raise PilotStartupAcquisitionUnavailable()
        # These constructors allocate duty holders only, with no native IO.
        # The actual outer owner must retain this object before acquire().
        self._sources = object.__new__(FixedStartupSourceReader)
        FixedStartupSourceReader.__init__(self._sources, source_uid, original_deadline)
        self._identity = object.__new__(FixedStartupIdentityReader)
        FixedStartupIdentityReader.__init__(self._identity, source_uid, original_deadline)
        self._thread = threading.current_thread()
        self._end, self._revision = original_deadline, original_revision
        self._state, self._cleanup, self._data = 'new', 'not-attempted', None
        self._fleet_targets_data = None

    def _owner(self):
        if threading.current_thread() is not self._thread:
            raise PilotStartupAcquisitionUnavailable()

    def _current_data(self):
        self._owner()
        if (self._state not in ('acquiring', 'retained') or
                not time.monotonic() < self._end):
            raise PilotStartupAcquisitionUnavailable()
        # Native diagnostics OUTSIDE all admission gates. The actual original
        # writer fence, not these repeated checks, must make the cohort atomic.
        self._sources._recheck()
        self._identity._recheck()
        if not time.monotonic() < self._end:
            raise PilotStartupAcquisitionUnavailable()

    def acquire(self):
        self._owner()
        if self._state != 'new':
            raise PilotStartupAcquisitionUnavailable()
        self._state = 'acquiring'
        first = None
        try:
            if not time.monotonic() < self._end:
                raise PilotStartupAcquisitionUnavailable()
            self._sources.open_fixed()
            self._identity.open_fixed()
            self._current_data()
            source_bytes = self._sources.read_sources()
            freq, users, roles = self._identity.read_inputs()
            self._current_data()
            # Complete duplicated freq bytes must agree. No document merge,
            # chosen alternative or parser-supplied callback can select input.
            parsed = decode_fixed_startup_inputs(source_bytes, freq, users, roles)
            self._current_data()
            data = prepare_configured_cohort_data(parsed, self._revision)
            self._current_data()
            if type(data) is not PilotConfiguredData:
                raise PilotStartupAcquisitionUnavailable()
            # Parse the SAME acquired hosts bytes outside admission gates.
            # Unsupported Fleet pair syntax does not change Cluster eligibility
            # or reuse another startup's result. Unexpected failures still take
            # the original failure/retirement path, without a successful value.
            fleet_targets = None
            try:
                fleet_targets = decode_fleet_target_bytes(source_bytes[1])
            except FleetTargetDataUnavailable:
                pass
            self._current_data()
            if (fleet_targets is not None and
                    type(fleet_targets) is not ConfiguredFleetTargetsData):
                raise PilotStartupAcquisitionUnavailable()
            self._data = data
            self._fleet_targets_data = fleet_targets
            self._state = 'retained'
            # Retain actual reader objects and their duties, not only copies.
            return self
        except BaseException as error:
            first = self._acquisition_failure = error
            self._acquisition_errors[0] = error
            self._state = 'failed'
        try:
            self.retire()
        except BaseException as cleanup:
            self._acquisition_errors[3] = cleanup
            first = _first(first, cleanup)
        self._acquisition_failure = first
        if first is not None and (not isinstance(first, Exception) or isinstance(first, MemoryError)):
            raise first
        raise PilotStartupAcquisitionUnavailable() from None

    def private_data(self):
        self._current_data()
        if self._state != 'retained' or type(self._data) is not PilotConfiguredData:
            raise PilotStartupAcquisitionUnavailable()
        # This same DATA object remains private and retained. Actual original
        # factory construction/final native admission still owes all real gates.
        return self._data

    def private_fleet_targets_data(self):
        """Same retained byte projection, outside gates; no endpoint grant.

        This repeats the original reader/currentness diagnostics, but never
        reparses, loads legacy configuration, expands targets or repairs data.
        The actual parent/writer/native owner and original response admission
        remain necessary. Callers must not invoke native diagnostics under an
        admission gate. No dispatcher or installation binding calls this yet.
        """
        self._current_data()
        if (self._state != 'retained' or
                type(self._fleet_targets_data) is not ConfiguredFleetTargetsData):
            raise PilotStartupAcquisitionUnavailable()
        return self._fleet_targets_data

    def retire(self):
        self._owner()
        self._state, self._data, self._fleet_targets_data = 'retired', None, None
        first = None
        if self._cleanup == 'not-attempted':
            self._cleanup = 'uncertain'
            try:
                self._sources.close()
            except BaseException as error:
                self._acquisition_errors[1] = error
                self._acquisition_failure = _first(self._acquisition_failure, error)
                first = error
            try:
                self._identity.close()
            except BaseException as error:
                self._acquisition_errors[2] = error
                self._acquisition_failure = _first(self._acquisition_failure, error)
                first = _first(first, error)
            if first is None:
                self._cleanup = 'locally-settled'
        # Preserve the same retained body/cleanup priority on every retirement.
        # A repeat must not demote an original Control or MemoryError to an
        # ordinary uncertainty, and never repeats either child close.
        failure = self._acquisition_failure
        if failure is not None and (not isinstance(failure, Exception) or isinstance(failure, MemoryError)):
            raise failure
        if first is not None:
            raise first
        if self._cleanup != 'locally-settled':
            raise PilotStartupAcquisitionClosureUncertain()
        # Neither local completion nor the state tuple proves physical closure
        # of native work with a lost return or the original worker process.

    def cleanup_observations(self):
        self._owner()
        return (self._state, self._cleanup, self._sources.close_observations(),
                self._identity.cleanup_observations())


# No native owner issuance, installation constructor, listener or admission.
