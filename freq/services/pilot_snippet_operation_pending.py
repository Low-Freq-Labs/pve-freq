"""Unregistered snippet operation/duty storage before any acquisition.

No operation identity, admission, result capture or physical owner is issued.
The custodian retains this staging object before its once-only preparation.
Actual registration and original return/cleanup interfaces remain unavailable.
"""
from freq.services.cluster_pilot_http import _RequestUnavailable


class _PendingSnippetDutyStorage:
    """An unacquired duty, never an outcome or a physically complete owner."""
    __slots__ = (
        '_owner', '_attempted', '_late_return', '_first_body_failure',
        '_first_retirement_failure', '_physical_state',
    )

    def __new__(cls):
        if cls is not _PendingSnippetDutyStorage:
            raise _RequestUnavailable()
        self = object.__new__(cls)
        self._owner = None
        self._attempted = False
        self._late_return = None
        self._first_body_failure = None
        self._first_retirement_failure = None
        self._physical_state = 'unacquired'
        return self

    def __init__(self):
        pass

    def __init_subclass__(cls, **kwargs):
        raise TypeError('pending snippet duty storage cannot be subclassed')

    def __copy__(self):
        raise TypeError('pending snippet duty storage cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('pending snippet duty storage cannot be copied')

    def __reduce_ex__(self, protocol):
        raise TypeError('pending snippet duty storage cannot be serialized')


    def _bind_pending_owner(self, operation):
        """Bind once, after this unacquired holder is retained in its slot.

        This records a private Python graph edge only. Matching types, phases
        and slots filter misuse; none establishes original external provenance,
        an admitted operation, resource ownership or positive currentness.
        A lost/failed return is handled by the retaining operation's existing
        preparation failure path. It must never allocate a replacement duty.
        """
        from freq.services.pilot_snippet_pending import _PendingOriginalSnippetCustodian
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(self) is not _PendingSnippetDutyStorage or
                type(operation) is not _PendingSnippetOperationStorage):
            raise _RequestUnavailable()
        custodian = operation._custodian
        if type(custodian) is not _PendingOriginalSnippetCustodian:
            raise _RequestUnavailable()
        original = custodian._owner
        if (type(original) is not OriginalPilotInstallation or
                original._snippet_custodian is not custodian or
                original._pending_state != 'preparing' or
                original._components_state != 'tables-ready' or
                original._pending_retirement_required is not False or
                original._live is not False or original._admission_uncertain is not False or
                original._server is not None or original._gate is not None or
                custodian._registration_staging is not operation or
                custodian._state != 'preparing' or custodian._uncertain is not False or
                operation._state != 'preparing' or operation._uncertain is not False or
                operation._operation_identity is not None or
                self._owner is not None or self._attempted is not False or
                self._late_return is not None or self._first_body_failure is not None or
                self._first_retirement_failure is not None or self._physical_state != 'unacquired' or
                sum(value is self for value in (
                    operation._content_duty, operation._input_duty, operation._child_duty,
                    operation._readback_duty, operation._parent_duty)) != 1):
            raise _RequestUnavailable()
        self._owner = operation

    def _retain_body_failure(self, error):
        """Retain first storage evidence only; caller owns original provenance.

        No exception formatting, currentness gate, return capture or physical
        outcome is involved. Later higher-priority errors must still reach the
        original caller's separate outward-selection policy.
        That trusted caller serializes this same retained holder; this method
        acquires no lock and proves no concurrent ordering.
        """
        if type(self) is not _PendingSnippetDutyStorage or not issubclass(type(error), BaseException):
            raise _RequestUnavailable()
        if self._first_body_failure is None:
            self._first_body_failure = error

    def _retain_retirement_failure(self, error):
        """Keep a separate first retirement error without discharging a duty.

        This intentionally does not require positive currentness. Original
        cleanup callers still must prove the same retained duty identity and
        attempt every independent duty; these storage methods do not do so.
        Caller serialization remains required; no lock is acquired here.
        """
        if type(self) is not _PendingSnippetDutyStorage or not issubclass(type(error), BaseException):
            raise _RequestUnavailable()
        if self._first_retirement_failure is None:
            self._first_retirement_failure = error


def _new_duty_storage():
    """Fixed pure allocation, not an injected factory or original resource."""
    return _PendingSnippetDutyStorage()


class _PendingSnippetOperationStorage:
    """Retained staging only; no registered/admitted operation is created."""
    __slots__ = (
        '_state', '_custodian', '_uncertain', '_operation_identity',
        '_content_duty', '_input_duty', '_child_duty', '_readback_duty',
        '_parent_duty', '_duties', '_errors', '_failure',
    )

    def __new__(cls):
        if cls is not _PendingSnippetOperationStorage:
            raise _RequestUnavailable()
        self = object.__new__(cls)
        self._state = 'allocated'
        self._custodian = None
        self._uncertain = False
        self._operation_identity = None
        self._content_duty = None
        self._input_duty = None
        self._child_duty = None
        self._readback_duty = None
        self._parent_duty = None
        self._duties = None
        self._failure = None
        self._errors = [None] * 3
        return self

    def __init__(self):
        pass

    def __init_subclass__(cls, **kwargs):
        raise TypeError('pending snippet operation storage cannot be subclassed')

    def __copy__(self):
        raise TypeError('pending snippet operation storage cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('pending snippet operation storage cannot be copied')

    def __reduce_ex__(self, protocol):
        raise TypeError('pending snippet operation storage cannot be serialized')

    def _prepare(self, custodian):
        """Preallocate unacquired holders in the already retained staging slot.

        This does not insert an operation into a registry, choose capacity,
        issue an identity, acquire a resource or accept supplied return data.
        All allocated duties remain reachable after failure; no retry/reset.
        """
        from freq.services.pilot_snippet_pending import (
            _PendingOriginalSnippetCustodian, _first_failure,
        )
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if type(custodian) is not _PendingOriginalSnippetCustodian:
            raise _RequestUnavailable()
        original = custodian._owner
        if (type(self) is not _PendingSnippetOperationStorage or
                type(original) is not OriginalPilotInstallation or
                original._snippet_custodian is not custodian or
                original._pending_state != 'preparing' or
                original._components_state != 'tables-ready' or
                original._pending_retirement_required is not False or
                original._live is not False or original._admission_uncertain is not False or
                original._server is not None or original._gate is not None or
                custodian._registration_staging is not self or
                custodian._state != 'preparing' or
                custodian._uncertain is not False or
                self._state != 'allocated' or self._custodian is not None or
                self._uncertain is not False or self._operation_identity is not None):
            raise _RequestUnavailable()
        self._state = 'preparing'
        self._custodian = custodian
        first = None
        try:
            self._content_duty = _new_duty_storage()
            _PendingSnippetDutyStorage._bind_pending_owner(self._content_duty, self)
            self._input_duty = _new_duty_storage()
            _PendingSnippetDutyStorage._bind_pending_owner(self._input_duty, self)
            self._child_duty = _new_duty_storage()
            _PendingSnippetDutyStorage._bind_pending_owner(self._child_duty, self)
            self._readback_duty = _new_duty_storage()
            _PendingSnippetDutyStorage._bind_pending_owner(self._readback_duty, self)
            self._parent_duty = _new_duty_storage()
            _PendingSnippetDutyStorage._bind_pending_owner(self._parent_duty, self)
            self._duties = (self._content_duty, self._input_duty,
                            self._child_duty, self._readback_duty, self._parent_duty)
            self._state = 'unregistered-storage'
            return
        except BaseException as error:
            first = self._failure = error
            self._errors[0] = error
        for index, (field, value) in enumerate((
                ('_state', 'retirement-only'), ('_uncertain', True)), 1):
            try:
                setattr(self, field, value)
            except BaseException as error:
                self._errors[index] = error
                first = _first_failure(first, error)
        self._failure = first
        if first is not None and (not issubclass(type(first), Exception) or issubclass(type(first), MemoryError)):
            raise first
        raise _RequestUnavailable() from None

    # No registry insertion, operation identity, capacity refund, result setter,
    # late-return capture, cleanup, registration retry, native or issuer method.
