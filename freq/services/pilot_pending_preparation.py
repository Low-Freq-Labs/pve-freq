"""First pure outside caller for canonical pending installation preparation.

The original top-level caller must retain this object before calling prepare.
This object retains the same pending installation before its table preparation.
There is no resource acquisition, native factory, activation or serving entry.
Imports are not claimed to be resource-free. Locally retained Python objects
and retirement flags never prove physical closure or positive currentness.
"""
import threading
from functools import wraps

from freq.services.cluster_pilot_startup import OriginalPilotInstallation
from freq.services.pilot_startup_acquisition import OriginalStartupInputAttempt
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.pilot_component_binding import _first_preparation_failure
from freq.services.pilot_snippet_pending import _PendingOriginalSnippetCustodian
from freq.services.pilot_snippet_operation_pending import _PendingSnippetOperationStorage


class OriginalPendingPreparation:
    """Once-only retained pure prefix; accepts no owner, callback or resource."""

    __slots__ = (
        '_state', '_installation', '_failure', '_errors', '_thread',
        '_retirement_started', '_retirement_errors', '_retirement_failure',
        '_startup_state', '_startup_errors', '_startup_failure',
    )

    def __new__(cls):
        if cls is not OriginalPendingPreparation:
            raise _RequestUnavailable()
        self = object.__new__(cls)
        self._state = 'allocated'
        self._installation = None
        self._failure = None
        self._errors = [None] * 6
        self._retirement_started = False
        self._retirement_errors = [None] * 10
        self._retirement_failure = None
        self._startup_state = 'unused'
        self._startup_errors = [None] * 8
        self._startup_failure = None
        self._thread = threading.current_thread()
        return self

    def __init__(self):
        # Reentry must never replace the original holder or failure storage.
        pass

    def __init_subclass__(cls, **kwargs):
        raise TypeError('original pending preparation cannot be subclassed')

    def __copy__(self):
        raise TypeError('original pending preparation cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('original pending preparation cannot be copied')

    def __reduce_ex__(self, protocol):
        raise TypeError('original pending preparation cannot be serialized')

    def prepare(self):
        """Retain before table allocation; all failure exits are retirement-only.

        Only the original allocating thread may prepare this holder. This is
        a local object identity filter, not native authority. No acquiring
        operation follows this method. A later real constructor
        must extend the original retained caller rather than treating this
        prepared state as permission to acquire, attach or publish resources.
        """
        if (type(self) is not OriginalPendingPreparation or
                threading.current_thread() is not self._thread or
                self._state != 'allocated' or self._installation is not None or
                self._failure is not None):
            raise _RequestUnavailable()
        # Consume the one attempt before allocating any pending object.
        self._state = 'preparing'
        try:
            # Canonical allocation is pure storage. Store its return before
            # invoking any preparation which can leave partially built tables.
            self._installation = OriginalPilotInstallation()
            OriginalPilotInstallation._prepare_pending_original(self._installation)
            self._state = 'prepared'
            return
        except BaseException as error:
            first = self._failure = error
            self._errors[0] = error
        self._state = 'retirement-only'
        installation = self._installation
        if installation is not None:
            # Attempt every independent quarantine assignment even if one
            # fails; keep the same object, tables, and failure obligations.
            for index, (field, value) in enumerate((
                    ('_pending_state', 'retirement-only'),
                    ('_pending_retirement_required', True),
                    ('_components_state', 'retirement-only'),
                    ('_live', False), ('_admission_uncertain', True)), 1):
                try:
                    setattr(installation, field, value)
                except BaseException as error:
                    self._errors[index] = error
                    first = _first_preparation_failure(first, error)
        self._failure = first
        if not issubclass(type(first), Exception) or issubclass(type(first), MemoryError):
            raise first
        raise _RequestUnavailable() from None


    def prepare_startup_inputs(self, source_uid, original_deadline, original_revision):
        """Retain the same pure startup attempt before its initializer.

        This prepares storage only. UID, deadline and revision are DATA passed
        unchanged to the existing initializer, never source authority. The
        original outer parent still owes its own retention and all native,
        writer, credential, lifetime and currentness gates before acquisition.
        A partial initializer is retained without attempting physical cleanup.
        """
        if (type(self) is not OriginalPendingPreparation or
                threading.current_thread() is not self._thread or
                self._state != 'prepared' or self._failure is not None or
                self._retirement_started is not False or
                self._startup_state != 'unused' or self._startup_failure is not None):
            raise _RequestUnavailable()
        installation = self._installation
        if (type(installation) is not OriginalPilotInstallation or
                installation._pending_state != 'prepared' or
                installation._pending_retirement_required is not False or
                installation._components_state != 'tables-ready' or
                installation._live is not False or
                installation._admission_uncertain is not False or
                installation._gate is not None or installation._server is not None or
                installation._startup_inputs is not None):
            raise _RequestUnavailable()
        # Spend before pure allocation, and retain its known return before init.
        self._startup_state = 'preparing'
        try:
            installation._startup_inputs = object.__new__(OriginalStartupInputAttempt)
            OriginalStartupInputAttempt.__init__(
                installation._startup_inputs, source_uid,
                original_deadline, original_revision)
            self._startup_state = 'prepared'
            return
        except BaseException as error:
            first = self._startup_failure = error
            self._startup_errors[0] = error
        # Every independent logical quarantine is attempted. Keep the partial
        # startup object and existing tables; do not guess missing cleanup fields.
        for index, (target, field, value) in enumerate((
                (self, '_startup_state', 'retirement-only'),
                (self, '_state', 'retirement-only'),
                (installation, '_pending_state', 'retirement-only'),
                (installation, '_pending_retirement_required', True),
                (installation, '_components_state', 'retirement-only'),
                (installation, '_live', False),
                (installation, '_admission_uncertain', True)), 1):
            try:
                setattr(target, field, value)
            except BaseException as error:
                self._startup_errors[index] = error
                first = _first_preparation_failure(first, error)
        self._startup_failure = first
        if not issubclass(type(first), Exception) or issubclass(type(first), MemoryError):
            raise first
        raise _RequestUnavailable() from None


    def retire_pending_storage(self):
        """Forbid further preparation; preserve the exact pending object graph.

        This serialized allocating-thread caller changes logical markers only.
        It never attempts resource cleanup, accepts a returned resource, erases
        a map, refunds capacity or claims physical closure. No positive native
        currentness is required. The real outside controller still owes exact
        original retention and all independently acquired physical duties.
        Repeating quarantine markers may not replace an earliest error.
        Outward selection includes the original preparation failure; a body
        Control retains priority over later ordinary retirement failures.
        """
        if (type(self) is not OriginalPendingPreparation or
                threading.current_thread() is not self._thread or
                self._state not in ('allocated', 'prepared', 'retirement-only')):
            raise _RequestUnavailable()
        self._retirement_started = True
        self._state = 'retirement-only'
        first = self._failure
        if self._startup_failure is not None:
            first = _first_preparation_failure(first, self._startup_failure)
        if self._retirement_failure is not None:
            first = _first_preparation_failure(first, self._retirement_failure)
        installation = self._installation
        if installation is None:
            self._retirement_failure = first
            if first is not None:
                if not issubclass(type(first), Exception) or issubclass(type(first), MemoryError):
                    raise first
                raise _RequestUnavailable() from None
            return
        if (type(installation) is not OriginalPilotInstallation or
                installation._live is not False or
                installation._server is not None or installation._gate is not None):
            error = _RequestUnavailable()
            if self._retirement_errors[9] is None:
                self._retirement_errors[9] = error
            first = _first_preparation_failure(first, error)
        else:
            # Independent assignments continue even after a sibling failure.
            for index, (field, value) in enumerate((
                    ('_pending_state', 'retirement-only'),
                    ('_pending_retirement_required', True),
                    ('_components_state', 'retirement-only'),
                    ('_live', False), ('_admission_uncertain', True))):
                try:
                    setattr(installation, field, value)
                except BaseException as error:
                    if self._retirement_errors[index] is None:
                        self._retirement_errors[index] = error
                    first = _first_preparation_failure(first, error)
            # Only locally retained exact pending classes are traversed. These
            # filters confer no resource provenance or permission to acquire.
            custodian = installation._snippet_custodian
            if custodian is not None:
                try:
                    if (type(custodian) is not _PendingOriginalSnippetCustodian or
                            custodian._owner is not None and custodian._owner is not installation):
                        raise _RequestUnavailable()
                    for index, (field, value) in enumerate((
                            ('_state', 'retirement-only'), ('_uncertain', True)), 5):
                        try:
                            setattr(custodian, field, value)
                        except BaseException as error:
                            if self._retirement_errors[index] is None:
                                self._retirement_errors[index] = error
                            first = _first_preparation_failure(first, error)
                    staging = custodian._registration_staging
                    if staging is not None:
                        if (type(staging) is not _PendingSnippetOperationStorage or
                                staging._custodian is not None and staging._custodian is not custodian):
                            raise _RequestUnavailable()
                        for index, (field, value) in enumerate((
                                ('_state', 'retirement-only'), ('_uncertain', True)), 7):
                            try:
                                setattr(staging, field, value)
                            except BaseException as error:
                                if self._retirement_errors[index] is None:
                                    self._retirement_errors[index] = error
                                first = _first_preparation_failure(first, error)
                except BaseException as error:
                    if self._retirement_errors[9] is None:
                        self._retirement_errors[9] = error
                    first = _first_preparation_failure(first, error)
        self._retirement_failure = first
        if first is not None:
            if not issubclass(type(first), Exception) or issubclass(type(first), MemoryError):
                raise first
            raise _RequestUnavailable() from None


# One process-local pure preparation root. This is not an installation,
# operation identity, durable registry, authority issuer or native factory.
# Module lifetime retains all returns/errors; no reset/replacement port exists.
# Ordinary local synchronization at import setup, not a qualified native job
# gate or original installation resource. Imports are not resource-free.
_ROOT_GATE = threading.Lock()
_ROOT_THREAD = threading.main_thread()
_ROOT_STARTED = False
_ROOT_STATE = 'unused'
_PENDING_ROOT = None
_ROOT_BODY_FAILURE = None
_ROOT_RETIREMENT_FAILURE = None
_ROOT_SELECTED_FAILURE = None
# Earliest wrapper-observed body and gate failures remain separate from the
# original operation errors; selected outward priority never erases evidence.
_ROOT_ENTRY_FAILURE = None
_ROOT_GATE_FAILURE = None
_ROOT_ENTRY_SELECTED_FAILURE = None


def _select_root_gate_failure(current, gate_error):
    """Combine stable original evidence; a later refusal cannot erase it.

    Per-entry outward selection may be an ordinary once-only guard refusal.
    Earliest caught entry failure and the original root operation's winner
    remain separate stable evidence. Include every actual nonNone failure
    before selecting this gate fault; do not use a None-only fallback.
    """
    first = _ROOT_ENTRY_FAILURE
    if _ROOT_SELECTED_FAILURE is not None:
        first = (_ROOT_SELECTED_FAILURE if first is None else
                 _first_preparation_failure(first, _ROOT_SELECTED_FAILURE))
    if current is not None:
        first = current if first is None else _first_preparation_failure(first, current)
    if _ROOT_ENTRY_SELECTED_FAILURE is not None:
        first = (_ROOT_ENTRY_SELECTED_FAILURE if first is None else
                 _first_preparation_failure(first, _ROOT_ENTRY_SELECTED_FAILURE))
    return gate_error if first is None else _first_preparation_failure(first, gate_error)


def _serialized_pending_root(method):
    @wraps(method)
    def invoke():
        global _ROOT_STARTED, _ROOT_STATE, _ROOT_GATE_FAILURE
        global _ROOT_ENTRY_FAILURE, _ROOT_ENTRY_SELECTED_FAILURE
        # A caught ownership-uncertain gate failure spends this local root.
        # No retry/release probe or new preparation may infer lock ownership.
        if _ROOT_GATE_FAILURE is not None:
            raise _RequestUnavailable()
        try:
            acquired = _ROOT_GATE.acquire(blocking=False)
        except BaseException as error:
            _ROOT_STARTED = True
            _ROOT_STATE = 'retirement-only'
            if _ROOT_GATE_FAILURE is None:
                _ROOT_GATE_FAILURE = error
            first = _select_root_gate_failure(None, error)
            _ROOT_ENTRY_SELECTED_FAILURE = first
            raise first
        if not acquired:
            # Known busy/reentry is not an uncertain ownership result. Leave
            # the outer root and all earliest evidence untouched.
            raise _RequestUnavailable()
        first = None
        result = None
        try:
            result = method()
        except BaseException as error:
            first = error
            if _ROOT_ENTRY_FAILURE is None:
                _ROOT_ENTRY_FAILURE = error
        try:
            # Exactly one attempt after known successful acquisition, including
            # body failure. A lost release return never authorizes retry.
            _ROOT_GATE.release()
        except BaseException as error:
            _ROOT_STARTED = True
            _ROOT_STATE = 'retirement-only'
            if _ROOT_GATE_FAILURE is None:
                _ROOT_GATE_FAILURE = error
            first = _select_root_gate_failure(first, error)
        _ROOT_ENTRY_SELECTED_FAILURE = first
        if first is not None:
            raise first
        return result
    return invoke


@_serialized_pending_root
def prepare_original_pending_root():
    """Retain the pending caller before preparation, once on the main Thread.

    Only pure Python storage is constructed. Losing any later call's return
    leaves the same module-retained caller/installation graph. An allocation
    failure before publishing that pure caller acquires no native resource and
    still consumes this attempt. Local main-Thread and exact class filters are
    not proof of an original service/controller identity or permission.
    """
    global _ROOT_STARTED, _ROOT_STATE, _PENDING_ROOT
    global _ROOT_BODY_FAILURE, _ROOT_RETIREMENT_FAILURE, _ROOT_SELECTED_FAILURE
    if threading.current_thread() is not _ROOT_THREAD or _ROOT_STARTED is not False:
        raise _RequestUnavailable()
    _ROOT_STARTED = True
    _ROOT_STATE = 'preparing'
    try:
        _PENDING_ROOT = OriginalPendingPreparation()
        OriginalPendingPreparation.prepare(_PENDING_ROOT)
        _ROOT_STATE = 'prepared'
        return
    except BaseException as error:
        _ROOT_BODY_FAILURE = error
        first = error
    _ROOT_STATE = 'retirement-only'
    # A successfully published pure caller stays retained after any failure.
    # Its logical marker path is independent of positive currentness and does
    # not pretend to discharge an actual physical resource duty.
    if _PENDING_ROOT is not None:
        try:
            OriginalPendingPreparation.retire_pending_storage(_PENDING_ROOT)
        except BaseException as error:
            if _ROOT_RETIREMENT_FAILURE is None:
                _ROOT_RETIREMENT_FAILURE = error
            first = _first_preparation_failure(first, error)
    _ROOT_SELECTED_FAILURE = first
    if not issubclass(type(first), Exception) or issubclass(type(first), MemoryError):
        raise first
    raise _RequestUnavailable() from None


@_serialized_pending_root
def retire_original_pending_root():
    """Keep the same local root and separately retained first failures.

    This is repeatable logical quarantine only, never permission to repeat an
    acquisition or physical cleanup. No map/holder/root/error is cleared and no
    closure result or handle is returned. Real native effects remain absent.
    """
    global _ROOT_STATE, _ROOT_RETIREMENT_FAILURE, _ROOT_SELECTED_FAILURE
    if threading.current_thread() is not _ROOT_THREAD or _ROOT_STARTED is not True:
        raise _RequestUnavailable()
    _ROOT_STATE = 'retirement-only'
    first = _ROOT_BODY_FAILURE
    if _ROOT_SELECTED_FAILURE is not None:
        first = _first_preparation_failure(first, _ROOT_SELECTED_FAILURE)
    if _PENDING_ROOT is not None:
        try:
            OriginalPendingPreparation.retire_pending_storage(_PENDING_ROOT)
        except BaseException as error:
            if _ROOT_RETIREMENT_FAILURE is None:
                _ROOT_RETIREMENT_FAILURE = error
            first = _first_preparation_failure(first, error)
    _ROOT_SELECTED_FAILURE = first
    if first is not None:
        if not issubclass(type(first), Exception) or issubclass(type(first), MemoryError):
            raise first
        raise _RequestUnavailable() from None


# No top-level CLI integration, resource constructor, positive native check,
# release/close receipt, source or credential reader, socket or listener.
