"""Original-parent retained node-token acquisition, uninstalled source only.

The actual source/request owner must retain this object before acquire, bind
its literal endpoint, principal and end to the actual configured cohort, and
enforce writer exclusion and physical retirement. This class does not issue
that owner, load trust, select a provider, admit a request or enable a service.
Private scalar values and same-object/type checks remain data, not authority.
"""
import re
import threading
import time

from freq.services.pilot_fixed_token_reader import (
    FixedNodeTokenReader, PilotCredentialUnavailable,
    PilotCredentialClosureUncertain,
)


_PART = re.compile(r'[A-Za-z0-9_.-]{1,128}', re.ASCII)


class OriginalNodeCredentialAttempt:
    """One private read/transfer and once retirement under an inherited end.

    Constructor inputs are retained original-parent DATA, not caller grants.
    configured_token_id is the exact parser's (principal, configured-name)
    tuple. Only its principal is used; the token's actual per-node name and
    fixed filename derive from the ORIGINAL endpoint spelling in the reader.
    No shared token/secret, endpoint, SSH, password or alternate path fallback.

    All diagnostics/read/serialization/close work belongs outside admission
    gates. Actual final native currentness and request admission remain the
    original parent's duty, including after private components are consumed.
    """
    __slots__ = ('_reader', '_principal', '_endpoint', '_end', '_thread',
                 '_state', '_cleanup', '_secret', '_components_taken',
                 '_failure', '_body_failure', '_cleanup_failure')

    def __init__(self, credential_uid, original_endpoint, configured_token_id,
                 original_end):
        if (type(configured_token_id) is not tuple or len(configured_token_id) != 2
                or any(type(value) is not str for value in configured_token_id)):
            raise PilotCredentialUnavailable()
        principal, configured_name = configured_token_id
        if not principal.isascii() or len(principal) > 257 or principal.count('@') != 1:
            raise PilotCredentialUnavailable()
        user, realm = principal.split('@')
        if any(_PART.fullmatch(value) is None
               for value in (user, realm, configured_name)):
            raise PilotCredentialUnavailable()
        # Allocate the actual native obligation holder before any syscall.
        # Reader construction also validates UID, literal endpoint and end.
        self._reader = FixedNodeTokenReader(credential_uid, original_endpoint,
                                             original_end)
        self._principal = principal
        self._endpoint = original_endpoint
        self._end = original_end
        self._thread = threading.current_thread()
        self._state = 'new'
        self._cleanup = 'not-attempted'
        self._secret = None
        self._components_taken = False
        self._failure = self._body_failure = self._cleanup_failure = None

    def _owner(self):
        if threading.current_thread() is not self._thread:
            raise PilotCredentialUnavailable()

    def _current_data(self):
        self._owner()
        if (self._state not in ('acquiring', 'retained', 'spent') or
                not time.monotonic() < self._end):
            raise PilotCredentialUnavailable()
        self._reader._recheck()
        if not time.monotonic() < self._end:
            raise PilotCredentialUnavailable()

    def acquire(self):
        """Read once into this retained original attempt, or retire and refuse.

        A missing/malformed/expired credential is unavailable; it never selects
        shared storage or creates/repairs a credential. Failed cleanup remains
        uncertain for the actual physical parent, including lost native calls.
        Caught controls and allocation failures propagate after independent
        retirement. Private body/cleanup failure references remain retained;
        they are not diagnostics or a complete outside-parent error ledger.
        """
        self._owner()
        if self._state != 'new':
            raise PilotCredentialUnavailable()
        self._state = 'acquiring'
        transferred = False
        original_error = None
        try:
            if not time.monotonic() < self._end:
                raise PilotCredentialUnavailable()
            self._reader.open_fixed()
            raw = self._reader.read_private_secret()
            self._current_data()
            # The fixed reader validates exactly UUID36 (optional final LF
            # removed) in its actual native same-file two-read operation.
            if type(raw) is not bytes or len(raw) != 36:
                raise PilotCredentialUnavailable()
            self._secret = raw.decode('ascii')
            self._current_data()
            self._state = 'retained'
            transferred = True
            return self
        except BaseException as error:
            original_error = self._body_failure = error
            # Any caught local failure still owes local retirement, including
            # a control between the local success flag and the return. A lost
            # successful OUTER return remains the original parent's duty.
            transferred = False
            self._state = 'failed'
        finally:
            if not transferred:
                try:
                    self.retire()
                except BaseException as cleanup:
                    self._cleanup_failure = cleanup
                    # First genuine control, then first allocation failure,
                    # then ordinary refusal. Decide AFTER independent cleanup;
                    # do not allocate a replacement refusal before retirement.
                    if (original_error is None or
                            isinstance(original_error, Exception) and (
                                not isinstance(cleanup, Exception) or
                                not isinstance(original_error, MemoryError) and
                                isinstance(cleanup, MemoryError))):
                        original_error = cleanup
        self._failure = original_error
        if (original_error is not None and (
                not isinstance(original_error, Exception) or isinstance(original_error, MemoryError))):
            raise original_error
        raise PilotCredentialUnavailable() from None

    def take_private_wire_components(self):
        """Consume one private scalar transfer; never a wire/admission grant.

        The actual read owner must retain this SAME attempt and its original
        source/credential/trust/request obligations through provider cleanup,
        parse and final admission. Returning a tuple cannot bind those duties.
        No secret value may enter diagnostics, files, logs or public responses.
        Python immutable copies are not claimed to be securely zeroized.
        """
        self._owner()
        if self._state != 'retained' or self._components_taken:
            raise PilotCredentialUnavailable()
        self._components_taken = True
        self._state = 'spent'
        self._current_data()
        token_name = self._reader.node_token_name
        if type(self._secret) is not str:
            raise PilotCredentialUnavailable()
        self._current_data()
        return self._principal, token_name, self._secret

    def retire(self):
        """Forget local secret and attempt each known reader close once.

        No numeric FD retry, renewed end or observation-to-authority conversion
        is permitted. Uncertain native duties stay retained in the reader for
        original physical retirement. A late return cannot revive this attempt.
        """
        self._owner()
        self._state = 'retired'
        self._components_taken = True
        self._secret = None
        if self._cleanup == 'not-attempted':
            self._cleanup = 'uncertain'
            self._reader.close()
            self._cleanup = 'locally-closed'
        if self._cleanup != 'locally-closed':
            raise PilotCredentialClosureUncertain()

    def cleanup_observations(self):
        self._owner()
        return self._state, self._cleanup, self._reader.close_observations()


# No issuer/factory, trust resolver, provider selector, service or entrypoint.
