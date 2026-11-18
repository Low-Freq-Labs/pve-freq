"""Original native auth input/decrypt/verification composition, WIP SOURCE.

This retains the actual fixed reader and decrypt operation, not copied input
bytes, a supplied configuration object, hash, verifier callback or factory.
The actual installation must retain this object before its first native call
and bind it to its original request and physically enforced writer fence.

This object is NOT an issued installation/auth lease. It cannot create sessions,
select a provider, admit a response or turn data equality into native authority.
No credential access, process invocation, import or test has been performed by
publishing it. Actual supervised native workload qualification remains absent.
"""
import re
import threading
import time

from freq.services.pilot_fixed_auth_reader import (
    FixedOriginalAuthReader, PilotAuthInputUnavailable,
    PilotAuthInputClosureUncertain,
)
from freq.services.pilot_readonly_inputs import (
    decode_retained_original_inputs, exact_original_auth_hash,
)
from freq.services.pilot_vault_read import OriginalVaultDecrypt


_USERNAME = re.compile(r'[a-z_][a-z0-9_-]{0,31}', re.ASCII)


def _first(first, later):
    if first is None or (isinstance(first, Exception) and (
            not isinstance(later, Exception) or
            not isinstance(first, MemoryError) and isinstance(later, MemoryError))):
        return later
    return first


class OriginalAuthInputAttempt:
    """Actual one-attempt input custody; private data until original admission.

    Distinct source/credential UIDs and the end are original parent DATA. Their
    shape or equality cannot prove the source/credential principal, native
    process, original request, writer exclusion or launch qualification. Never
    accept an arbitrary instance as a user/currentness/session grant.

    The parent must enforce the reviewed SIGCHLD/reaper conditions BEFORE
    Popen and through pidfd acquisition/reaping. This class does not implement
    that supervisor or infer it from a supplied Boolean or cleanup tuple.
    """
    __slots__ = ('_reader', '_decrypt', '_end', '_thread', '_state', '_cleanup',
                 '_user', '_role', '_hash', '_verify_started', '_verified',
                 '_input_errors', '_input_failure',
                 '_request_errors', '_request_failure', '_request_retirement_started')

    def __init__(self, source_uid, credential_uid, original_deadline):
        # Spend this same initializer before holder allocation. Re-entry must
        # not replace retained native duty holders or renew the original end.
        if type(self) is not OriginalAuthInputAttempt or hasattr(self, '_state'):
            raise PilotAuthInputUnavailable()
        self._state = 'constructing'
        self._input_errors = [None] * 4
        self._input_failure = None
        # Separate per-attempt original broker failure duties; never a shared
        # component-wide ledger across concurrent request attempts.
        self._request_errors = [None] * 3
        self._request_failure = None
        self._request_retirement_started = False
        # Both complete native duty holders precede every effectful call.
        self._reader = FixedOriginalAuthReader(source_uid, credential_uid,
                                               original_deadline)
        self._decrypt = OriginalVaultDecrypt()
        self._end = original_deadline
        self._thread = threading.current_thread()
        self._state = 'new'
        self._cleanup = 'not-attempted'
        self._user = self._role = self._hash = None
        self._verify_started = self._verified = False

    def _owner(self):
        if threading.current_thread() is not self._thread:
            raise PilotAuthInputUnavailable()

    def _current_data(self):
        self._owner()
        if self._state not in ('acquiring', 'retained', 'verified'):
            raise PilotAuthInputUnavailable()
        if not time.monotonic() < self._end:
            raise PilotAuthInputUnavailable()
        # Native diagnostic outside ALL admission gates. This is not final
        # source currentness: only the original physical writer fence can make
        # the retained cohort eligible for the later atomic admission.
        self._reader._recheck()
        if not time.monotonic() < self._end:
            raise PilotAuthInputUnavailable()

    def _decrypt_locally_settled(self):
        process, selector, keys, streams, pidfd, kill, wait = (
            self._decrypt.cleanup_observations())
        return (process in ('unused', 'reaped') and
                selector in ('unused', 'closed') and
                all(s in ('unused', 'closed') for s in keys + streams) and
                pidfd in ('unused', 'closed') and
                wait in ('unused', 'reaped'))

    def acquire(self, configured_username):
        """Read once and retain private actual user/hash input, or refuse.

        A native-confirmed absent user/hash is invalid credentials (None), not
        store initialization. Any uncertain/malformed input/cleanup is fixed
        unavailable. The actual owner still must retain/revalidate this SAME
        attempt under the genuine original request/source fence before use.
        """
        self._owner()
        if self._state != 'new':
            raise PilotAuthInputUnavailable()
        self._state = 'acquiring'
        transferred = False
        original_error = None
        try:
            if (type(configured_username) is not str or
                    _USERNAME.fullmatch(configured_username) is None or
                    not time.monotonic() < self._end):
                raise PilotAuthInputUnavailable()
            self._reader.open_fixed()
            config, users, roles, ciphertext, machine_id = self._reader.read_inputs()
            self._current_data()
            nodes, configured_users, service_user, token_id = (
                decode_retained_original_inputs(config, users, roles))
            # The read application never turns a service principal into a
            # browser user, invents admin, or repairs an absent user registry.
            role = next((r for u, r in configured_users
                         if u == configured_username), None)
            self._current_data()
            if configured_username == service_user or role is None:
                return None
            plaintext = self._decrypt.run(ciphertext, machine_id,
                                           original_deadline=self._end)
            self._current_data()
            if plaintext is None or not self._decrypt_locally_settled():
                raise PilotAuthInputUnavailable()
            stored = exact_original_auth_hash(plaintext, configured_username)
            self._current_data()
            if stored is None:
                return None
            self._user, self._role, self._hash = configured_username, role, stored
            self._state = 'retained'
            transferred = True
            # Private original input attempt, never a copied tuple/hash grant.
            return self
        except BaseException as error:
            original_error = self._input_failure = error
            self._input_errors[0] = error
            self._state = 'failed'
            if not isinstance(error, Exception) or isinstance(error, MemoryError):
                raise
            raise PilotAuthInputUnavailable() from None
        finally:
            if not transferred:
                first = original_error
                try:
                    self.retire()
                except BaseException as cleanup:
                    self._input_errors[3] = cleanup
                    selected = _first(first, cleanup)
                    self._input_failure = selected
                    if selected is not first or first is None:
                        raise selected

    @property
    def original_user(self):
        self._current_data()
        return self._user

    @property
    def role(self):
        self._current_data()
        return self._role

    def verify_password(self, password):
        """Original algorithm, once, outside all admission gates; data only.

        The actual owner must test its retained original attempt and request
        plus the private outcome at final admission. This return alone cannot
        authorize anything. No caller supplies a hash, hasher or result flag.
        """
        self._owner()
        if self._state != 'retained' or self._verify_started:
            raise PilotAuthInputUnavailable()
        self._verify_started = True
        try:
            self._current_data()
            if type(password) is not str:
                raise PilotAuthInputUnavailable()
            # The selected frozen original module owns the original algorithm
            # and eventual actual session/rate stores. Do not copy a fake auth
            # module or reintroduce its legacy login/config/Vault write paths.
            from freq.api.auth import verify_password
            verified = verify_password(password, self._hash)
            self._current_data()
            if type(verified) is not bool:
                raise PilotAuthInputUnavailable()
            self._verified = verified
            self._state = 'verified'
            return verified
        except BaseException:
            self._verified = False
            self._state = 'failed'
            raise

    def retire(self):
        """Retire locally once; uncertain native duties remain for the parent.

        Local observations do not authenticate physical closure of a lost
        syscall or original worker. Every known descriptor gets its independent
        once-close. No new wait budget or repeat numeric close is introduced.
        """
        self._owner()
        self._state = 'retired'
        self._user = self._role = self._hash = None
        self._verified = False
        if self._cleanup == 'not-attempted':
            self._cleanup = 'uncertain'
            first = None
            try:
                self._reader.close()
            except BaseException as error:
                self._input_errors[1] = error
                self._input_failure = _first(self._input_failure, error)
                first = error
            try:
                if not self._decrypt_locally_settled():
                    raise PilotAuthInputClosureUncertain()
            except BaseException as error:
                self._input_errors[2] = error
                self._input_failure = _first(self._input_failure, error)
                first = _first(first, error)
            if first is not None:
                raise first
            self._cleanup = 'locally-settled'
        if self._cleanup != 'locally-settled':
            raise PilotAuthInputClosureUncertain()

    def cleanup_observations(self):
        self._owner()
        return (self._state, self._cleanup,
                self._reader.cleanup_observations(),
                self._decrypt.cleanup_observations())


# No OriginalPilotInstallation issuer, listener, session map or response writer.
