"""Fixed auth methods for the future original native installation class.

Actual startup must inherit this class only in its concrete original factory.
That factory, original native bootstrap and its physical lifetime are still
absent. These methods cannot construct an installation or turn an application
object, callback, receipt, class check or component into native authority.
"""
from freq.services.cluster_pilot_http import _OriginalPilotServer, _RequestUnavailable
from freq.services.pilot_auth_attempts import OriginalPilotAuthAttempts
from freq.services.pilot_auth_commit import OriginalAuthCommit


class _OriginalPilotAuthForwards:
    """No state or constructor, and no alternate auth stores or fallbacks.

    All arguments pass unchanged to the SAME constructor-retained component.
    Its original gates perform native-currentness/final admission and original
    once-write accounting. Forwarding never treats auth_current as admission.
    The original factory must retain component identities for its whole native
    lifetime, including failed/uncertain work, and prevent external mutation.
    """
    __slots__ = ()

    def _original_auth_owner(self):
        try:
            from freq.services.cluster_pilot_startup import OriginalPilotInstallation
        except ImportError:
            raise _RequestUnavailable() from None
        if type(self) is not OriginalPilotInstallation:
            raise _RequestUnavailable()
        server = getattr(self, '_server', None)
        if (type(server) is not _OriginalPilotServer or
                server._cluster_pilot_installation is not self):
            raise _RequestUnavailable()
        return server

    def _original_auth_attempts(self):
        server = self._original_auth_owner()
        component = getattr(self, '_auth_inputs', None)
        if (type(component) is not OriginalPilotAuthAttempts or
                component._installation is not self or
                component._broker is not server._pilot_requests):
            raise _RequestUnavailable()
        return component

    def _original_auth_commit(self):
        server = self._original_auth_owner()
        component = getattr(self, '_auth_commit', None)
        if (type(component) is not OriginalAuthCommit or
                component._installation is not self or
                component._broker is not server._pilot_requests or
                component._references is not self._references):
            raise _RequestUnavailable()
        return component

    def begin_auth(self, handler, username):
        return self._original_auth_attempts().begin_auth(handler, username)

    def auth_current(self, attempt):
        return self._original_auth_attempts().auth_current(attempt)

    def retire_auth(self, attempt):
        # Do not require live admission here: the SAME retained cleanup duty
        # must remain reachable after retirement/quarantine. The component
        # performs once cleanup and retains every unsettled original duty.
        return self._original_auth_attempts().retire_auth(attempt)

    def admit_login(self, handler, attempt):
        return self._original_auth_commit().admit_login(handler, attempt)

    def admit_verify(self, handler):
        return self._original_auth_commit().admit_verify(handler)

    def admit_logout(self, handler):
        return self._original_auth_commit().admit_logout(handler)

    def write_admitted_response(self, handler, response):
        return self._original_auth_commit().write_admitted_response(handler, response)


# No real installation class, positive native factory, component construction,
# server/SSLContext/source/credential IO, mutation, lock, grant or activation.
