"""Unacquired original journal connector storage; no connection constructor.

The installation retains its custodian, which retains this blank holder before
preparation. These graph checks only refuse misuse. They cannot establish that
the original outside parent, directory owner or native custodian exists.
"""
from freq.services.cluster_pilot_http import _RequestUnavailable


class _PendingJournalStageStorage:
    """Separate future entered/returned/raw slots, initially all unacquired."""
    __slots__ = ('_connector', '_entered', '_returned', '_value',
                 '_body_failure', '_cleanup_failure', '_state')

    def __new__(cls):
        if cls is not _PendingJournalStageStorage:
            raise _RequestUnavailable()
        self = object.__new__(cls)
        self._connector = None
        self._entered = self._returned = False
        self._value = self._body_failure = self._cleanup_failure = None
        self._state = 'unacquired'
        return self

    def __init__(self):
        pass

    def __init_subclass__(cls, **kwargs):
        raise TypeError('pending journal stage cannot be subclassed')

    def __copy__(self):
        raise TypeError('pending journal stage cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('pending journal stage cannot be copied')

    def __reduce_ex__(self, protocol):
        raise TypeError('pending journal stage cannot be serialized')


def _new_stage_storage():
    """Pure fixed allocation; no supplied factory or resource acquisition."""
    return _PendingJournalStageStorage()


class _PendingOriginalSnippetJournal:
    """Once-prepared storage only, never a qualified journal or admission."""
    __slots__ = (
        '_state',
        '_custodian',
        '_uncertain',
        '_preparation_entered',
        '_preparation_returned',
        '_reentered',
        '_failure',
        '_errors',
        '_directory',
        '_database',
        '_connection',
        '_configuration',
        '_schema',
        '_transaction',
        '_cursor',
        '_snapshot',
        '_close',
        '_stages',
        '_original_stages',
        '_original_directory',
        '_original_database',
        '_original_connection',
        '_original_configuration',
        '_original_schema',
        '_original_transaction',
        '_original_cursor',
        '_original_snapshot',
        '_original_close',
        '_errors_original',
        '_body_failure',
        '_state_failure',
        '_uncertain_failure',
        '_recording_failure',
        '_error_mirror_intact',
    )

    def __new__(cls):
        if cls is not _PendingOriginalSnippetJournal:
            raise _RequestUnavailable()
        self = object.__new__(cls)
        self._state = 'allocated'
        self._custodian = None
        self._uncertain = False
        self._preparation_entered = self._preparation_returned = False
        self._reentered = False
        self._failure = None
        self._errors = [None] * 3
        self._errors_original = self._errors
        self._body_failure = self._state_failure = None
        self._uncertain_failure = self._recording_failure = None
        self._error_mirror_intact = True
        self._directory = self._database = self._connection = None
        self._configuration = self._schema = self._transaction = None
        self._cursor = self._snapshot = self._close = self._stages = None
        self._original_stages = None
        self._original_directory = self._original_database = self._original_connection = None
        self._original_configuration = self._original_schema = self._original_transaction = None
        self._original_cursor = self._original_snapshot = self._original_close = None
        return self

    def __init__(self):
        # Repeated Python initialization cannot erase a spent preparation.
        pass

    def __init_subclass__(cls, **kwargs):
        raise TypeError('pending journal connector cannot be subclassed')

    def __copy__(self):
        raise TypeError('pending journal connector cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('pending journal connector cannot be copied')

    def __reduce_ex__(self, protocol):
        raise TypeError('pending journal connector cannot be serialized')

    def _prepare(self, custodian):
        """Bind the original caller-retained unacquired stage holders.

        No path, URI, database, descriptor, connection, SQL, lock, callback or
        credential is accepted or acquired. Lost pure allocation returns grant
        no retry of this same preparation or any future acquiring operation.
        """
        from freq.services.pilot_snippet_pending import _PendingOriginalSnippetCustodian
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if type(self) is not _PendingOriginalSnippetJournal:
            raise _RequestUnavailable()
        if self._preparation_entered is not False:
            self._reentered = True
            raise _RequestUnavailable()
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
                custodian._journal_pending is not self or custodian._journal_original is not self or
                custodian._state != 'preparing' or custodian._uncertain is not False or
                self._state != 'allocated' or self._custodian is not None or
                self._uncertain is not False or self._reentered is not False or
                self._preparation_returned is not False or self._failure is not None or
                type(self._errors) is not list or len(self._errors) != 3 or
                any(error is not None for error in self._errors) or
                any(value is not None for value in (
                    self._directory, self._database, self._connection, self._configuration,
                    self._schema, self._transaction, self._cursor, self._snapshot,
                    self._close, self._stages, self._original_stages,
                    self._original_directory, self._original_database, self._original_connection,
                    self._original_configuration, self._original_schema, self._original_transaction,
                    self._original_cursor, self._original_snapshot, self._original_close))):
            raise _RequestUnavailable()
        self._preparation_entered = True
        self._state = 'preparing'
        self._custodian = custodian
        directory = database = connection = configuration = schema = transaction = cursor = snapshot = close = None
        originals = None
        errors_original = self._errors_original
        try:
            try:
                # These originals were returned to and retained by the caller.
                # This helper binds them; it does not allocate replacement stages.
                originals = custodian._journal_stage_roots
                if (type(originals) is not tuple or len(originals) != 9 or
                        any(type(stage) is not _PendingJournalStageStorage for stage in originals) or
                        any(originals[i] is originals[j] for i in range(9) for j in range(i))):
                    raise _RequestUnavailable()
                directory, database, connection, configuration, schema, transaction, cursor, snapshot, close = originals
                if any(originals[i] is not value for i, value in enumerate((
                        custodian._journal_original_directory, custodian._journal_original_database, custodian._journal_original_connection, custodian._journal_original_configuration, custodian._journal_original_schema, custodian._journal_original_transaction, custodian._journal_original_cursor, custodian._journal_original_snapshot, custodian._journal_original_close))):
                    raise _RequestUnavailable()
                self._original_directory = self._directory = directory
                stage = directory
                if (stage._connector is not None or stage._entered is not False or
                        stage._returned is not False or stage._value is not None or
                        stage._body_failure is not None or stage._cleanup_failure is not None or
                        type(stage._state) is not str or stage._state != 'unacquired'):
                    raise _RequestUnavailable()
                stage._connector = self
                self._original_database = self._database = database
                stage = database
                if (stage._connector is not None or stage._entered is not False or
                        stage._returned is not False or stage._value is not None or
                        stage._body_failure is not None or stage._cleanup_failure is not None or
                        type(stage._state) is not str or stage._state != 'unacquired'):
                    raise _RequestUnavailable()
                stage._connector = self
                self._original_connection = self._connection = connection
                stage = connection
                if (stage._connector is not None or stage._entered is not False or
                        stage._returned is not False or stage._value is not None or
                        stage._body_failure is not None or stage._cleanup_failure is not None or
                        type(stage._state) is not str or stage._state != 'unacquired'):
                    raise _RequestUnavailable()
                stage._connector = self
                self._original_configuration = self._configuration = configuration
                stage = configuration
                if (stage._connector is not None or stage._entered is not False or
                        stage._returned is not False or stage._value is not None or
                        stage._body_failure is not None or stage._cleanup_failure is not None or
                        type(stage._state) is not str or stage._state != 'unacquired'):
                    raise _RequestUnavailable()
                stage._connector = self
                self._original_schema = self._schema = schema
                stage = schema
                if (stage._connector is not None or stage._entered is not False or
                        stage._returned is not False or stage._value is not None or
                        stage._body_failure is not None or stage._cleanup_failure is not None or
                        type(stage._state) is not str or stage._state != 'unacquired'):
                    raise _RequestUnavailable()
                stage._connector = self
                self._original_transaction = self._transaction = transaction
                stage = transaction
                if (stage._connector is not None or stage._entered is not False or
                        stage._returned is not False or stage._value is not None or
                        stage._body_failure is not None or stage._cleanup_failure is not None or
                        type(stage._state) is not str or stage._state != 'unacquired'):
                    raise _RequestUnavailable()
                stage._connector = self
                self._original_cursor = self._cursor = cursor
                stage = cursor
                if (stage._connector is not None or stage._entered is not False or
                        stage._returned is not False or stage._value is not None or
                        stage._body_failure is not None or stage._cleanup_failure is not None or
                        type(stage._state) is not str or stage._state != 'unacquired'):
                    raise _RequestUnavailable()
                stage._connector = self
                self._original_snapshot = self._snapshot = snapshot
                stage = snapshot
                if (stage._connector is not None or stage._entered is not False or
                        stage._returned is not False or stage._value is not None or
                        stage._body_failure is not None or stage._cleanup_failure is not None or
                        type(stage._state) is not str or stage._state != 'unacquired'):
                    raise _RequestUnavailable()
                stage._connector = self
                self._original_close = self._close = close
                stage = close
                if (stage._connector is not None or stage._entered is not False or
                        stage._returned is not False or stage._value is not None or
                        stage._body_failure is not None or stage._cleanup_failure is not None or
                        type(stage._state) is not str or stage._state != 'unacquired'):
                    raise _RequestUnavailable()
                stage._connector = self
                if (self._directory is not directory or self._original_directory is not directory or
                        self._database is not database or self._original_database is not database or
                        self._connection is not connection or self._original_connection is not connection or
                        self._configuration is not configuration or self._original_configuration is not configuration or
                        self._schema is not schema or self._original_schema is not schema or
                        self._transaction is not transaction or self._original_transaction is not transaction or
                        self._cursor is not cursor or self._original_cursor is not cursor or
                        self._snapshot is not snapshot or self._original_snapshot is not snapshot or
                        self._close is not close or self._original_close is not close):
                    raise _RequestUnavailable()
                self._original_stages = originals
                self._stages = originals
                # Full direct checks AFTER binding the caller originals.
                # No project helper runs between this barrier and publication.
                if (original._snippet_custodian is not custodian or
                        custodian._owner is not original or custodian._journal_pending is not self or custodian._journal_original is not self or
                        original._pending_state != 'preparing' or
                        original._components_state != 'tables-ready' or
                        original._pending_retirement_required is not False or
                        original._live is not False or original._admission_uncertain is not False or
                        original._server is not None or original._gate is not None or
                        custodian._state != 'preparing' or custodian._uncertain is not False or
                        self._custodian is not custodian or self._state != 'preparing' or
                        self._uncertain is not False or self._preparation_entered is not True or
                        self._preparation_returned is not False or self._reentered is not False or
                        self._failure is not None or type(self._errors) is not list or
                        len(self._errors) != 3 or any(error is not None for error in self._errors) or
                        any(type(stage) is not _PendingJournalStageStorage for stage in self._stages) or
                        any(self._stages[i] is self._stages[j]
                            for i in range(9) for j in range(i))):
                    raise _RequestUnavailable()
                for stage in self._stages:
                    if (stage._connector is not self or stage._entered is not False or
                            stage._returned is not False or stage._value is not None or
                            stage._body_failure is not None or stage._cleanup_failure is not None or
                            type(stage._state) is not str or stage._state != 'unacquired'):
                        raise _RequestUnavailable()
                if (self._errors is not errors_original or self._errors_original is not errors_original or
                        self._body_failure is not None or self._state_failure is not None or
                        self._uncertain_failure is not None or self._recording_failure is not None or
                        self._error_mirror_intact is not True or type(errors_original) is not list or
                        len(errors_original) != 3 or any(error is not None for error in errors_original)):
                    raise _RequestUnavailable()
                self._state = 'unacquired-storage'
                self._preparation_returned = True
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
            # Restore every known normal original AFTER all helpers, even
            # when they replaced canonical/current views and then raised.
            self._original_directory = directory
            self._original_database = database
            self._original_connection = connection
            self._original_configuration = configuration
            self._original_schema = schema
            self._original_transaction = transaction
            self._original_cursor = cursor
            self._original_snapshot = snapshot
            self._original_close = close
            self._original_stages = originals

    def _pending_storage_ready(self, custodian):
        """Read-only inactive storage filter; never original provenance."""
        from freq.services.pilot_snippet_pending import _PendingOriginalSnippetCustodian
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        if type(self) is not _PendingOriginalSnippetJournal or type(custodian) is not _PendingOriginalSnippetCustodian:
            return False
        try:
            if (self._errors is not self._errors_original or
                    self._body_failure is not None or self._state_failure is not None or
                    self._uncertain_failure is not None or self._recording_failure is not None or
                    self._error_mirror_intact is not True):
                return False
            original = custodian._owner
            if (type(original) is not OriginalPilotInstallation or
                    original._snippet_custodian is not custodian or
                    original._pending_state != 'prepared' or
                    original._components_state not in ('tables-ready', 'construction-pending') or
                    original._pending_retirement_required is not False or
                    original._live is not False or original._admission_uncertain is not False or
                    custodian._journal_pending is not self or custodian._journal_original is not self or self._custodian is not custodian or
                    custodian._state != 'prepared' or custodian._uncertain is not False or
                    self._state != 'unacquired-storage' or self._uncertain is not False or
                    self._preparation_entered is not True or self._preparation_returned is not True or
                    self._reentered is not False or self._failure is not None or
                    type(self._errors) is not list or len(self._errors) != 3 or
                    any(error is not None for error in self._errors)):
                return False
            stages = self._stages
            if (type(stages) is not tuple or len(stages) != 9 or
                    custodian._journal_stage_roots is not stages or
                    any(stages[i] is not value for i, value in enumerate((
                        custodian._journal_original_directory, custodian._journal_original_database, custodian._journal_original_connection, custodian._journal_original_configuration, custodian._journal_original_schema, custodian._journal_original_transaction, custodian._journal_original_cursor, custodian._journal_original_snapshot, custodian._journal_original_close))) or
                    self._original_stages is not stages or
                    stages[0] is not self._original_directory or
                    stages[1] is not self._original_database or
                    stages[2] is not self._original_connection or
                    stages[3] is not self._original_configuration or
                    stages[4] is not self._original_schema or
                    stages[5] is not self._original_transaction or
                    stages[6] is not self._original_cursor or
                    stages[7] is not self._original_snapshot or
                    stages[8] is not self._original_close or
                    any(type(stage) is not _PendingJournalStageStorage for stage in stages) or
                    any(stages[i] is stages[j] for i in range(9) for j in range(i)) or
                    stages != (self._directory, self._database, self._connection,
                               self._configuration, self._schema, self._transaction,
                               self._cursor, self._snapshot, self._close)):
                return False
            for stage in stages:
                if (stage._connector is not self or stage._entered is not False or
                        stage._returned is not False or stage._value is not None or
                        stage._body_failure is not None or stage._cleanup_failure is not None or
                        type(stage._state) is not str or stage._state != 'unacquired'):
                    return False
            return True
        except AttributeError:
            return False

    # No acquire/configure/SQL/transaction/read/close/attach/admit/issue method.
