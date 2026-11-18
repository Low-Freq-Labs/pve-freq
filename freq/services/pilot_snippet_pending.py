"""Pending snippet operation storage, before any original resource acquisition.

This is not a snippet issuer, native custodian, durable ledger or permission
source. Its exact original parent retains it before once-only preparation.
All tables are private Python storage. No method admits or dispatches work.
"""
from freq.services.cluster_pilot_http import _RequestUnavailable
from freq.services.pilot_snippet_operation_pending import _PendingSnippetOperationStorage
from freq.services.pilot_snippet_journal_pending import (
    _PendingOriginalSnippetJournal, _PendingJournalStageStorage, _new_stage_storage,
)


def _empty_table():
    """Fixed pure allocation, never a supplied constructor or callback."""
    return {}


def _first_failure(first, later):
    if first is None or (issubclass(type(first), Exception) and (
            not issubclass(type(later), Exception) or
            not issubclass(type(first), MemoryError) and issubclass(type(later), MemoryError))):
        return later
    return first


class _PendingOriginalSnippetCustodian:
    """One retained pending object; matching type/parent is only a filter."""
    __slots__ = (
        '_state',
        '_owner',
        '_uncertain',
        '_operations',
        '_versions',
        '_physical_duties',
        '_retired_operations',
        '_tables',
        '_errors',
        '_failure',
        '_registration_staging',
        '_journal_pending',
        '_journal_original',
        '_journal_stage_roots',
        '_journal_prepare_pending',
        '_journal_prepare_return',
        '_journal_original_directory',
        '_journal_original_database',
        '_journal_original_connection',
        '_journal_original_configuration',
        '_journal_original_schema',
        '_journal_original_transaction',
        '_journal_original_cursor',
        '_journal_original_snapshot',
        '_journal_original_close',
        '_errors_original',
        '_body_failure',
        '_state_failure',
        '_uncertain_failure',
        '_recording_failure',
        '_error_mirror_intact',
    )

    def __new__(cls):
        if cls is not _PendingOriginalSnippetCustodian:
            raise _RequestUnavailable()
        self = object.__new__(cls)
        # Pure storage only. A failure here has acquired no original resource.
        self._state = 'allocated'
        self._owner = None
        self._uncertain = False
        self._operations = None
        self._versions = None
        self._physical_duties = None
        self._retired_operations = None
        self._tables = None
        self._registration_staging = None
        self._journal_pending = self._journal_original = None
        self._journal_stage_roots = None
        self._journal_prepare_pending = False
        self._journal_prepare_return = None
        self._journal_original_directory = None
        self._journal_original_database = None
        self._journal_original_connection = None
        self._journal_original_configuration = None
        self._journal_original_schema = None
        self._journal_original_transaction = None
        self._journal_original_cursor = None
        self._journal_original_snapshot = None
        self._journal_original_close = None
        self._failure = None
        self._errors = [None] * 3
        self._errors_original = self._errors
        self._body_failure = self._state_failure = None
        self._uncertain_failure = self._recording_failure = None
        self._error_mirror_intact = True
        return self

    def __init__(self):
        # Repeated Python initialization never resets tables or spent state.
        pass

    def __init_subclass__(cls, **kwargs):
        raise TypeError('pending snippet storage cannot be subclassed')

    def __copy__(self):
        raise TypeError('pending snippet storage cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('pending snippet storage cannot be copied')

    def __reduce_ex__(self, protocol):
        raise TypeError('pending snippet storage cannot be serialized')

    def _pending_storage_ready(self, owner):
        """Read-only storage filter before and during inactive construction.

        The caller still owes original provenance, serialization, all-writer
        currentness and native resource custody. This filter acquires nothing,
        repairs nothing and grants no admission. It is never a cleanup gate.
        Missing/corrupt storage refuses; allocation/control failures propagate
        to the original retaining caller rather than being treated as absence.
        """
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        from freq.services.pilot_snippet_operation_pending import _PendingSnippetDutyStorage
        if (type(self) is not _PendingOriginalSnippetCustodian or
                type(owner) is not OriginalPilotInstallation):
            return False
        try:
            if (self._errors is not self._errors_original or
                    self._body_failure is not None or self._state_failure is not None or
                    self._uncertain_failure is not None or self._recording_failure is not None or
                    self._error_mirror_intact is not True):
                return False
            if (owner._snippet_custodian is not self or self._owner is not owner or
                    type(owner._pending_state) is not str or owner._pending_state != 'prepared' or
                    type(owner._components_state) is not str or
                    owner._components_state not in ('tables-ready', 'construction-pending') or
                    owner._pending_retirement_required is not False or
                    owner._pending_preparation_failure is not None or
                    owner._component_preparation_failure is not None or
                    owner._live is not False or owner._admission_uncertain is not False or
                    type(self._state) is not str or self._state != 'prepared' or
                    self._uncertain is not False or self._failure is not None):
                return False
            tables = self._tables
            if (type(tables) is not tuple or len(tables) != 4 or
                    any(type(table) is not dict for table in tables) or
                    any(tables[i] is tables[j] for i in range(4) for j in range(i)) or
                    self._operations is not tables[0] or self._versions is not tables[1] or
                    self._physical_duties is not tables[2] or self._retired_operations is not tables[3] or
                    any(tables)):
                return False
            operation = self._registration_staging
            if (type(operation) is not _PendingSnippetOperationStorage or
                    operation._custodian is not self or
                    type(operation._state) is not str or operation._state != 'unregistered-storage' or
                    operation._uncertain is not False or operation._operation_identity is not None or
                    operation._failure is not None):
                return False
            duties = operation._duties
            if (type(duties) is not tuple or len(duties) != 5 or
                    any(type(duty) is not _PendingSnippetDutyStorage for duty in duties) or
                    any(duties[i] is duties[j] for i in range(5) for j in range(i)) or
                    operation._content_duty is not duties[0] or
                    operation._input_duty is not duties[1] or operation._child_duty is not duties[2] or
                    operation._readback_duty is not duties[3] or operation._parent_duty is not duties[4]):
                return False
            for duty in duties:
                if (duty._owner is not operation or duty._attempted is not False or
                        duty._late_return is not None or duty._first_body_failure is not None or
                        duty._first_retirement_failure is not None or
                        type(duty._physical_state) is not str or duty._physical_state != 'unacquired'):
                    return False
            for errors in (self._errors, operation._errors):
                if type(errors) is not list or len(errors) != 3 or any(error is not None for error in errors):
                    return False
            journal = self._journal_pending
            stages = self._journal_stage_roots
            # Direct original-caller filter; no delegated helper follows it.
            if (self._journal_original is not journal or
                    type(journal) is not _PendingOriginalSnippetJournal or
                    self._journal_prepare_pending is not False or self._journal_prepare_return is not None or
                    type(stages) is not tuple or len(stages) != 9 or
                    journal._stages is not stages or journal._original_stages is not stages or
                    journal._custodian is not self or journal._state != 'unacquired-storage' or
                    journal._preparation_entered is not True or
                    journal._preparation_returned is not True or journal._reentered is not False or
                    journal._uncertain is not False or journal._failure is not None or
                    journal._errors is not journal._errors_original or
                    journal._body_failure is not None or journal._state_failure is not None or
                    journal._uncertain_failure is not None or journal._recording_failure is not None or
                    journal._error_mirror_intact is not True or
                    type(journal._errors) is not list or len(journal._errors) != 3 or
                    any(error is not None for error in journal._errors) or
                    any(type(stage) is not _PendingJournalStageStorage for stage in stages) or
                    any(stages[i] is stages[j] for i in range(9) for j in range(i))):
                return False
            if any(stages[i] is not value for i, value in enumerate((
                    self._journal_original_directory, self._journal_original_database, self._journal_original_connection, self._journal_original_configuration, self._journal_original_schema, self._journal_original_transaction, self._journal_original_cursor, self._journal_original_snapshot, self._journal_original_close))):
                return False
            if any(stages[i] is not value for i, value in enumerate((
                    journal._original_directory, journal._original_database, journal._original_connection, journal._original_configuration, journal._original_schema, journal._original_transaction, journal._original_cursor, journal._original_snapshot, journal._original_close))):
                return False
            if any(stages[i] is not value for i, value in enumerate((
                    journal._directory, journal._database, journal._connection, journal._configuration, journal._schema, journal._transaction, journal._cursor, journal._snapshot, journal._close))):
                return False
            for stage in stages:
                if (stage._connector is not journal or stage._entered is not False or
                        stage._returned is not False or stage._value is not None or
                        stage._body_failure is not None or stage._cleanup_failure is not None or
                        type(stage._state) is not str or stage._state != 'unacquired'):
                    return False
            return True
        except AttributeError:
            return False

    def _prepare(self, owner):
        """Once-only map allocation after the exact pending parent retains us.

        No lock, clock, content, credential, child, descriptor or IO is acquired.
        A partial failure leaves every already allocated table in this same
        parent-retained object and permanently forbids preparation retries.
        The caller must retain this object even after retirement or lost return.
        """
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if (type(self) is not _PendingOriginalSnippetCustodian or
                type(owner) is not OriginalPilotInstallation or
                owner._snippet_custodian is not self or
                owner._pending_state != 'preparing' or
                owner._components_state != 'tables-ready' or
                owner._pending_retirement_required is not False or
                owner._live is not False or owner._admission_uncertain is not False or
                owner._server is not None or owner._gate is not None or
                self._state != 'allocated' or self._owner is not None or
                self._uncertain is not False or self._journal_pending is not None or
                self._journal_original is not None or self._journal_stage_roots is not None or
                self._journal_prepare_pending is not False or self._journal_prepare_return is not None or
                any(value is not None for value in (self._journal_original_directory, self._journal_original_database, self._journal_original_connection, self._journal_original_configuration, self._journal_original_schema, self._journal_original_transaction, self._journal_original_cursor, self._journal_original_snapshot, self._journal_original_close))):
            raise _RequestUnavailable()
        self._state = 'preparing'
        self._owner = owner
        first = None
        journal = None
        journal_errors_original = None
        journal_stage_roots = None
        journal_prepare_pending = False
        journal_prepare_return = None
        directory = database = connection = configuration = schema = transaction = cursor = snapshot = close = None
        errors_original = self._errors_original
        try:
            try:
                self._operations = _empty_table()
                self._versions = _empty_table()
                self._physical_duties = _empty_table()
                self._retired_operations = _empty_table()
                # Retain unregistered storage before its own duty allocations.
                # This never inserts an operation or acquires an original resource.
                self._registration_staging = _PendingSnippetOperationStorage()
                _PendingSnippetOperationStorage._prepare(self._registration_staging, self)
                # Retain this pure connector holder before its storage preparation.
                # Original directory/file/connection acquisition remains absent.
                journal = _PendingOriginalSnippetJournal()
                self._journal_original = journal
                self._journal_pending = journal
                # Capture this known original BEFORE the fallible child helper.
                journal_errors_original = journal._errors_original
                # Original caller owns every normal blank BEFORE delegated binding.
                directory = _new_stage_storage()
                self._journal_original_directory = directory
                database = _new_stage_storage()
                self._journal_original_database = database
                connection = _new_stage_storage()
                self._journal_original_connection = connection
                configuration = _new_stage_storage()
                self._journal_original_configuration = configuration
                schema = _new_stage_storage()
                self._journal_original_schema = schema
                transaction = _new_stage_storage()
                self._journal_original_transaction = transaction
                cursor = _new_stage_storage()
                self._journal_original_cursor = cursor
                snapshot = _new_stage_storage()
                self._journal_original_snapshot = snapshot
                close = _new_stage_storage()
                self._journal_original_close = close
                journal_stage_roots = (directory, database, connection, configuration, schema, transaction, cursor, snapshot, close)
                self._journal_stage_roots = journal_stage_roots
                journal_prepare_pending = self._journal_prepare_pending = True
                journal_prepare_return = _PendingOriginalSnippetJournal._prepare(journal, self)
                self._journal_prepare_return = journal_prepare_return
                journal_prepare_pending = self._journal_prepare_pending = False
                # Compare current views against SAME normal blank, never reread it.
                if (owner._snippet_custodian is not self or self._owner is not owner or
                        owner._pending_state != 'preparing' or
                        owner._components_state != 'tables-ready' or
                        owner._pending_retirement_required is not False or
                        owner._live is not False or owner._admission_uncertain is not False or
                        owner._server is not None or owner._gate is not None or
                        self._state != 'preparing' or self._uncertain is not False or
                        self._journal_pending is not journal or
                        self._journal_original is not journal or
                        journal_prepare_return is not None or
                        self._journal_prepare_return is not journal_prepare_return or
                        self._journal_prepare_pending is not False or
                        self._journal_stage_roots is not journal_stage_roots or
                        any(value is not original for value, original in zip(
                            (self._journal_original_directory, self._journal_original_database, self._journal_original_connection, self._journal_original_configuration, self._journal_original_schema, self._journal_original_transaction, self._journal_original_cursor, self._journal_original_snapshot, self._journal_original_close),
                            journal_stage_roots)) or
                        journal._stages is not journal_stage_roots or
                        journal._original_stages is not journal_stage_roots or
                        type(journal) is not _PendingOriginalSnippetJournal or
                        journal._custodian is not self or journal._state != 'unacquired-storage' or
                        journal._preparation_entered is not True or
                        journal._preparation_returned is not True or journal._reentered is not False or
                        journal._uncertain is not False or journal._failure is not None or
                        journal._errors is not journal_errors_original or
                        journal._errors_original is not journal_errors_original or
                        journal._body_failure is not None or journal._state_failure is not None or
                        journal._uncertain_failure is not None or journal._recording_failure is not None or
                        journal._error_mirror_intact is not True or
                        type(journal._errors) is not list or len(journal._errors) != 3 or
                        any(error is not None for error in journal._errors) or
                        journal._original_stages is not journal._stages or
                        type(journal._stages) is not tuple or len(journal._stages) != 9 or
                        any(type(stage) is not _PendingJournalStageStorage for stage in journal._stages) or
                        any(journal._stages[i] is journal._stages[j]
                            for i in range(9) for j in range(i)) or
                        any(journal._stages[i] is not value for i, value in enumerate((
                            journal._original_directory, journal._original_database, journal._original_connection,
                            journal._original_configuration, journal._original_schema, journal._original_transaction,
                            journal._original_cursor, journal._original_snapshot, journal._original_close))) or
                        any(journal._stages[i] is not value for i, value in enumerate((
                            journal._directory, journal._database, journal._connection,
                            journal._configuration, journal._schema, journal._transaction,
                            journal._cursor, journal._snapshot, journal._close)))):
                    raise _RequestUnavailable()
                for stage in journal._stages:
                    if (stage._connector is not journal or stage._entered is not False or
                            stage._returned is not False or stage._value is not None or
                            stage._body_failure is not None or stage._cleanup_failure is not None or
                            type(stage._state) is not str or stage._state != 'unacquired'):
                        raise _RequestUnavailable()
                self._tables = (self._operations, self._versions,
                                self._physical_duties, self._retired_operations)
                if (self._errors is not errors_original or self._errors_original is not errors_original or
                        self._body_failure is not None or self._state_failure is not None or
                        self._uncertain_failure is not None or self._recording_failure is not None or
                        self._error_mirror_intact is not True or type(errors_original) is not list or
                        len(errors_original) != 3 or any(error is not None for error in errors_original)):
                    raise _RequestUnavailable()
                self._state = 'prepared'
                return
            except BaseException as error:
                first = body_failure = error
                self._body_failure = self._failure = error
            # Fixed roots are authoritative; malformed mutable mirror is not
            # indexed and cannot prevent either independent retirement attempt.
            state_failure = uncertain_failure = recording_failure = None
            try:
                setattr(self, '_state', 'retirement-only')
            except BaseException as error:
                state_failure = error
            try:
                setattr(self, '_uncertain', True)
            except BaseException as error:
                uncertain_failure = error
            mirror_intact = False
            try:
                if (self._errors is errors_original and type(errors_original) is list and
                        len(errors_original) == 3):
                    errors_original[0] = body_failure
                    errors_original[1] = state_failure
                    errors_original[2] = uncertain_failure
                    mirror_intact = (len(errors_original) == 3 and
                                     errors_original[0] is body_failure and
                                     errors_original[1] is state_failure and
                                     errors_original[2] is uncertain_failure)
            except BaseException as error:
                recording_failure = error
            # Preserve actual local Control > Memory > ordinary policy inline;
            # all observed raw roots remain independent of the selected winner.
            for error in (state_failure, uncertain_failure, recording_failure):
                if error is not None and (issubclass(type(first), Exception) and (
                        not issubclass(type(error), Exception) or
                        not issubclass(type(first), MemoryError) and issubclass(type(error), MemoryError))):
                    first = error
            # No compatibility write or project helper follows this fixed tail.
            self._body_failure = body_failure
            self._state_failure = state_failure
            self._uncertain_failure = uncertain_failure
            self._recording_failure = recording_failure
            self._error_mirror_intact = mirror_intact
            self._errors_original = errors_original
            self._failure = first
            self._state = 'retirement-only'
            self._uncertain = True
            if not issubclass(type(first), Exception) or issubclass(type(first), MemoryError):
                raise first
            raise _RequestUnavailable() from None
        finally:
            self._errors_original = errors_original
            # Last direct stores, including failures of later recording helpers.
            # Current substituted view is never repaired or adopted.
            self._journal_original = journal
            if journal_errors_original is not None:
                # Retain the known original, leaving substituted current views untouched.
                journal._errors_original = journal_errors_original
            # Every known normal return survives even partial/failed binding.
            self._journal_original_directory = directory
            self._journal_original_database = database
            self._journal_original_connection = connection
            self._journal_original_configuration = configuration
            self._journal_original_schema = schema
            self._journal_original_transaction = transaction
            self._journal_original_cursor = cursor
            self._journal_original_snapshot = snapshot
            self._journal_original_close = close
            self._journal_stage_roots = journal_stage_roots
            self._journal_prepare_pending = journal_prepare_pending
            self._journal_prepare_return = journal_prepare_return
            if type(journal) is _PendingOriginalSnippetJournal:
                journal._original_directory = directory
                journal._original_database = database
                journal._original_connection = connection
                journal._original_configuration = configuration
                journal._original_schema = schema
                journal._original_transaction = transaction
                journal._original_cursor = cursor
                journal._original_snapshot = snapshot
                journal._original_close = close
                journal._original_stages = journal_stage_roots

    # No issue, admit, write, readback, publish, clear/refund, close, retry,
    # factory, attach, activation or positive native-currentness operation.
