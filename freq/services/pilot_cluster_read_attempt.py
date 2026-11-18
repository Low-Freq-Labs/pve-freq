"""Private node credential -> fixed TLS exchange -> observed parser composition.

Uninstalled source, NOT an original installation/credential/trust issuer.
The actual native parent must reserve the fixed named payload before trust/credential
resolution and retain this SAME attempt before its first effect, under its
original request, source/cohort, trust and physical retirement obligations.
Private body/retirement/post-cleanup failures and the three independent close
records remain on this SAME attempt. No input value, exact class, context or
returned body grants admission.
Trust acquisition uses only the fixed existing system bundle and SAME original
literal endpoint IP. There is no TLS-name/context constructor argument.
"""
import math
import threading
import time

from freq.services.cluster_observation_exchange import (
    OriginalClusterExchange, NAMED_PAYLOAD_RESERVATION as EXCHANGE_PAYLOAD_RESERVATION,
)
from freq.services.cluster_observation_profile import WireTarget
from freq.services.cluster_report.cluster_observation_browser import (
    prepare_private_observation, PUBLIC_BODY_LIMIT,
)
from freq.services.pilot_node_credential_attempt import OriginalNodeCredentialAttempt
from freq.services.pilot_fixed_trust_reader import FixedSystemTrustReader


# Named logical simultaneous CA byte-buffer/PEM allowance, not total RSS or
# native certificate/OpenSSL allocation containment. The actual parent owes
# its separate physical allowance BEFORE any trust or credential acquisition.
TRUST_INPUT_RESERVATION = 6 * 1048576 + 3
NAMED_PAYLOAD_RESERVATION = EXCHANGE_PAYLOAD_RESERVATION + TRUST_INPUT_RESERVATION


class PilotPrivateReadUnavailable(Exception):
    def __init__(self):
        super().__init__('Cluster observation unavailable')


class PilotPrivateReadClosureUncertain(PilotPrivateReadUnavailable):
    pass


def _first(first, later):
    if first is None or (isinstance(first, Exception) and (
            not isinstance(later, Exception) or
            not isinstance(first, MemoryError) and isinstance(later, MemoryError))):
        return later
    return first


class OriginalPrivateClusterRead:
    """One private prepared body, cleanup before return, no final publication.

    The enclosing original owner must charge NAMED_PAYLOAD_RESERVATION before
    any trust/credential acquisition; this class accepts no supplied reservation flag or granting token.
    It must retain actual credential and CA/TLS-name sources, immutable trust
    context, request/session/reference/cohort/writer-fence and resources through
    final ordered admission. Source diagnostics cannot establish those duties.

    All work below is outside admission gates. Logical byte/step/time checks
    do not prove total RSS, native preemption, lost syscall recovery or physical
    closure; the independently qualified original outer parent remains liable.
    """
    __slots__ = ('_credential', '_trust', '_recipient', '_exchange', '_target', '_context', '_end',
                 '_thread', '_state', '_cleanup', '_exchange_started',
                 '_exchange_clean_return', '_body_failure', '_retirement_failure',
                 '_finish_failure', '_failure', '_cleanup_states',
                 '_cleanup_returns', '_cleanup_failures', '_closure_failure')

    def __init__(self, credential_uid, original_endpoint, configured_token_id,
                 original_end):
        if type(original_end) is not float or not math.isfinite(original_end):
            raise PilotPrivateReadUnavailable()
        # These allocations perform no credential/socket IO. The actual parent
        # retains this complete obligation holder BEFORE calling run.
        self._recipient = original_endpoint
        self._trust = FixedSystemTrustReader(original_endpoint, original_end)
        self._credential = OriginalNodeCredentialAttempt(
            credential_uid, original_endpoint, configured_token_id, original_end)
        self._exchange = OriginalClusterExchange()
        # WireTarget canonicalizes only transport scalars. Credential filename
        # and token-name remain tied to the ORIGINAL literal endpoint above.
        # Cluster serializer ignores node for its fixed /cluster/status path.
        self._target = WireTarget(original_endpoint, original_endpoint, 'configured')
        self._context = None
        self._end = original_end
        self._thread = threading.current_thread()
        self._state = 'new'
        self._cleanup = 'not-attempted'
        self._exchange_started = self._exchange_clean_return = False
        self._body_failure = self._retirement_failure = None
        self._finish_failure = self._failure = self._closure_failure = None
        # Fixed-size private records exist before any acquiring effect.
        # An unresolved pending call remains visible to the physical parent.
        self._cleanup_states = ['unused', 'unused', 'unused']
        self._cleanup_returns = [None, None, None]
        self._cleanup_failures = [None, None, None]

    def _owner(self):
        if threading.current_thread() is not self._thread:
            raise PilotPrivateReadUnavailable()

    def _current_data(self):
        self._owner()
        if self._state != 'running' or not time.monotonic() < self._end:
            raise PilotPrivateReadUnavailable()

    def run(self, observation_ref):
        """Return provisional canonical private bytes or None, exactly once.

        observation_ref is a bounded correlation scalar, not a binding grant.
        Only the actual original read route may consume its retained binding,
        retain this same attempt/result and finally admit the response. No
        provider retry, alternate endpoint/trust, fallback or partial output.
        """
        self._owner()
        if self._state != 'new':
            raise PilotPrivateReadUnavailable()
        self._state = 'running'
        first = None
        failed = False
        components = native_body = prepared = None
        try:
            self._current_data()
            if (type(observation_ref) is not str or len(observation_ref) != 32 or
                    any(c not in '0123456789abcdef' for c in observation_ref)):
                raise PilotPrivateReadUnavailable()
            self._trust.open_fixed()
            self._current_data()
            self._trust.build_private_context()
            self._current_data()
            recipient, self._context = self._trust.private_components()
            if recipient != self._recipient:
                raise PilotPrivateReadUnavailable()
            self._current_data()
            if self._credential.acquire() is not self._credential:
                raise PilotPrivateReadUnavailable()
            self._current_data()
            components = self._credential.take_private_wire_components()
            self._current_data()
            self._exchange_started = True  # Before any possible socket effect.
            native_body = self._exchange.run(self._target, components, self._context,
                                             original_deadline=self._end)
            components = None
            self._current_data()
            # Dedicated collector already caps raw full JSON before allocation;
            # this final scalar guard does not substitute a new parser/stream.
            if type(native_body) is not bytes or len(native_body) > 1048576:
                raise PilotPrivateReadUnavailable()
            # The fixed ORIGINAL exchange returns bytes only after successful
            # once-close; None/exception cannot establish that source fact.
            self._exchange_clean_return = True
            self._credential._current_data()
            self._trust._recheck()
            prepared = prepare_private_observation(native_body, observation_ref)
            native_body = None
            self._current_data()
            self._credential._current_data()
            self._trust._recheck()
            if type(prepared) is not bytes or not 0 < len(prepared) <= PUBLIC_BODY_LIMIT:
                raise PilotPrivateReadUnavailable()
        except BaseException as error:
            failed = True
            first = self._body_failure = error
        finally:
            components = native_body = None
            try:
                self.retire()
            except BaseException as cleanup:
                failed = True
                self._retirement_failure = cleanup
                first = _first(first, cleanup)
        # Cleanup cannot renew the same original end. Clock failure also cannot
        # turn provisional bytes into success or replace an earlier control.
        try:
            if not time.monotonic() < self._end:
                failed = True
        except BaseException as error:
            failed = True
            self._finish_failure = error
            first = _first(first, error)
        self._failure = first
        if first is not None and (not isinstance(first, Exception) or isinstance(first, MemoryError)):
            raise first
        if (failed or self._state != 'retired' or self._cleanup != 'locally-closed'):
            return None
        return prepared

    def retire(self):
        """Retire once; independent original socket, credential and trust cleanup.

        Original exchange already closes its socket before returning. Its same
        once-consumed holder prevents any repeated numeric close here. Earlier
        credential/parse/clock failures still retire all original holders.
        Trust context/pending native allocation stays retained in SAME _trust
        for actual parent process retirement, even after known FD closes.
        locally-closed means these local socket/file duties only. It never
        means OpenSSL allocation or whole process physically retired.
        Any uncertain close or lost work stays with the physical parent.
        """
        self._owner()
        self._state = 'retired'
        self._context = None
        if self._cleanup == 'not-attempted':
            self._cleanup = 'uncertain'
            first = None
            if self._exchange_started and not self._exchange_clean_return:
                self._closure_failure = PilotPrivateReadClosureUncertain()
                first = self._closure_failure
            self._exchange._retired = True
            # Each known original close is attempted independently. Capture
            # the call before entry, its actual return, or its exact failure.
            # No diagnostic export or repeated numerical close is introduced.
            self._cleanup_states[0] = 'pending'
            try:
                self._cleanup_returns[0] = self._exchange._socket_owner.close()
                self._cleanup_states[0] = 'returned'
            except BaseException as error:
                self._cleanup_failures[0] = error
                self._cleanup_states[0] = 'raised'
                first = _first(first, error)
            self._cleanup_states[1] = 'pending'
            try:
                self._cleanup_returns[1] = self._credential.retire()
                self._cleanup_states[1] = 'returned'
            except BaseException as error:
                self._cleanup_failures[1] = error
                self._cleanup_states[1] = 'raised'
                first = _first(first, error)
            self._cleanup_states[2] = 'pending'
            try:
                self._cleanup_returns[2] = self._trust.close()
                self._cleanup_states[2] = 'returned'
            except BaseException as error:
                self._cleanup_failures[2] = error
                self._cleanup_states[2] = 'raised'
                first = _first(first, error)
            if self._exchange._busy:
                if self._closure_failure is None:
                    self._closure_failure = PilotPrivateReadClosureUncertain()
                first = _first(first, self._closure_failure)
            if first is not None:
                self._retirement_failure = first
                raise first
            self._cleanup = 'locally-closed'
        if self._cleanup != 'locally-closed':
            # Never replace a retained first cleanup failure on repetition.
            # An interrupted/lost outer return with no known failure remains
            # uncertain, with pending records intact and no native retry.
            if self._retirement_failure is not None:
                raise self._retirement_failure
            raise PilotPrivateReadClosureUncertain()

    def cleanup_observations(self):
        self._owner()
        socket_owner = self._exchange._socket_owner
        return (self._state, self._cleanup, self._credential.cleanup_observations(),
                self._exchange._busy, self._exchange._spent,
                socket_owner._spent, socket_owner._socket is None,
                self._exchange_started, self._exchange_clean_return,
                self._trust.close_observations(), self._trust._context_state)


# No original source/trust factory, issuer, binding consume, dispatcher or write.
