"""Fixed-path HTTPS operations for one locally registered QEMU lab guest.

No retry, redirect, proxy or SSH path exists. Five-second cooperative native
deadlines reject late results; synchronous OS DNS cannot be forcibly cancelled.
The caller must separately revalidate registration and provider guest identity,
hold returned UPIDs server-side, and resolve uncertain submission outcomes.
"""

import http.client
import json
import math
import re
import ssl
import sys
import time
from urllib.parse import quote

from .lab_guest_registration import Registration, RegistrationError, read_ca, read_token_secret, valid_provider


MAX_BODY = 2 * 1024 * 1024
CALL_TIMEOUT = 5.0


class LabTransportError(Exception):
    def __init__(self, code, uncertain=False):
        self.code = code
        self.uncertain = uncertain
        super().__init__(code)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise LabTransportError("invalid_response")
        result[key] = value
    return result


def _constant(_value):
    raise LabTransportError("invalid_response")


def _float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise LabTransportError("invalid_response")
    return parsed


class LabPveTransport:
    def __init__(self, registration):
        if (not isinstance(registration, Registration) or not valid_provider(registration.provider)
                or type(registration.node) is not str
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}", registration.node)
                or registration.guest_type != "qemu" or type(registration.vmid) is not int
                or not 0 < registration.vmid <= 2**53 - 1):
            raise LabTransportError("registration_unavailable")
        self.registration = registration
        self.before_submit = None
        self.deadline = None
        self.current = None
        self._guest_path = "/api2/json/nodes/{}/qemu/{}".format(quote(registration.node, safe=""), registration.vmid)

    def get_config(self):
        return self._call("GET", self._guest_path + "/config", dict)

    def get_status(self):
        return self._call("GET", self._guest_path + "/status/current", dict)

    def get_permissions(self):
        path = quote("/vms/{}".format(self.registration.vmid), safe="")
        return self._call("GET", "/api2/json/access/permissions?path=" + path, dict)

    def submit(self, action):
        if (type(action) is not str or action not in ("start", "shutdown")
                or action not in self.registration.allowed_actions):
            raise LabTransportError("invalid_action")
        return self._call("POST", self._guest_path + "/status/" + action, str,
                          body=b"" if action == "start" else b"forceStop=0&timeout=30")

    def get_task(self, upid):
        # The API caller must obtain this value from its own retained operation,
        # never accept an arbitrary client-supplied provider task selector.
        if not self._valid_upid(upid):
            raise LabTransportError("invalid_task")
        path = "/api2/json/nodes/{}/tasks/{}/status".format(
            quote(self.registration.node, safe=""), quote(upid, safe=""))
        return self._call("GET", path, dict)

    def _valid_upid(self, upid):
        return (type(upid) is str and 0 < len(upid) <= 512
                and re.fullmatch(
                    r"UPID:" + re.escape(self.registration.node)
                    + r":[0-9A-Fa-f]{8}:[0-9A-Fa-f]{8,16}:[0-9A-Fa-f]{8}:"
                    + r"[A-Za-z0-9_-]{1,64}:[A-Za-z0-9_.-]{0,128}:[A-Za-z0-9_.@!+-]{1,128}:", upid) is not None)

    def _call(self, method, path, expected, body=None):
        state = {"attempted": False}
        try:
            return self._native(method, path, expected, body, state)
        except MemoryError:
            raise
        except LabTransportError as failure:
            raise LabTransportError(failure.code, uncertain=state["attempted"]) from None
        except RegistrationError:
            raise LabTransportError("credentials_unavailable", uncertain=state["attempted"]) from None
        except ssl.SSLError:
            raise LabTransportError("tls_unavailable", uncertain=state["attempted"]) from None
        except (ValueError, UnicodeError, RecursionError, http.client.IncompleteRead):
            raise LabTransportError("invalid_response", uncertain=state["attempted"]) from None
        except Exception:
            raise LabTransportError("provider_unavailable", uncertain=state["attempted"]) from None

    def _native(self, method, path, expected, body, state):
        end = time.monotonic() + CALL_TIMEOUT
        if self.deadline is not None:
            if type(self.deadline) not in (int, float) or not math.isfinite(self.deadline):
                raise LabTransportError("provider_unavailable")
            end = min(end, self.deadline)

        def remaining():
            if self.current is not None:
                try:
                    if self.current() is not True:
                        raise LabTransportError("session_retired")
                except MemoryError:
                    raise
                except Exception:
                    raise LabTransportError("session_retired") from None
            left = end - time.monotonic()
            if left <= 0:
                raise LabTransportError("provider_unavailable")
            return min(CALL_TIMEOUT, left)

        registration = self.registration
        # Read each protected credential anew before any native network call.
        remaining()
        secret = read_token_secret(registration.token_secret_file)
        if (type(registration.token_id) is not str or len(registration.token_id) > 256
                or not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+![A-Za-z0-9_.-]+", registration.token_id)):
            raise LabTransportError("credentials_unavailable")
        remaining()
        read_ca(registration.ca_file)
        remaining()
        try:
            context = ssl.create_default_context(cafile=registration.ca_file)
        except MemoryError:
            raise
        except Exception:
            raise LabTransportError("tls_unavailable") from None
        if context.check_hostname is not True or context.verify_mode != ssl.CERT_REQUIRED:
            raise LabTransportError("tls_unavailable")
        connection = http.client.HTTPSConnection(registration.provider, 8006,
                                                 timeout=remaining(), context=context)
        response = None
        try:
            connection.connect()
            transport = connection.sock
            transport.settimeout(remaining())
            headers = {"Authorization": "PVEAPIToken=" + registration.token_id + "=" + secret,
                       "Accept": "application/json", "Accept-Encoding": "identity"}
            if method == "POST":
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                # Revalidate after credential reads and TLS connect, immediately
                # before the one request may cross the provider boundary.
                if self.before_submit is not None:
                    self.before_submit()
                state["attempted"] = True
            connection.request(method, path, body=body, headers=headers)
            transport.settimeout(remaining())
            response = connection.getresponse()
            if response.status != 200:
                raise LabTransportError("provider_unavailable")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise LabTransportError("invalid_response")
            length = response.getheader("Content-Length")
            if length is not None and (not length.isascii() or not length.isdecimal()
                                       or len(length) > 10 or int(length) > MAX_BODY):
                raise LabTransportError("invalid_response")
            payload = bytearray()
            while True:
                transport.settimeout(remaining())
                chunk = response.read1(min(65536, MAX_BODY + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > MAX_BODY:
                    raise LabTransportError("invalid_response")
                if response.isclosed():
                    break
            remaining()
            if length is not None and len(payload) != int(length):
                raise LabTransportError("invalid_response")
            document = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs,
                                  parse_constant=_constant, parse_float=_float)
            if (type(document) is not dict or set(document) != {"data"}
                    or type(document["data"]) is not expected
                    or (expected is str and not self._valid_upid(document["data"]))):
                raise LabTransportError("invalid_response")
            remaining()
            return document["data"]
        finally:
            pending = sys.exception()
            cleanup = None
            # A will-close response is detached by HTTPSConnection.getresponse;
            # it independently owns its buffered reader and underlying socket.
            # Attempt both cleanup legs even after a genuine interruption.
            for owned in (response, connection):
                if owned is None:
                    continue
                try:
                    owned.close()
                except BaseException as failure:
                    if cleanup is None or (isinstance(cleanup, Exception)
                            and not isinstance(cleanup, MemoryError)
                            and (isinstance(failure, MemoryError)
                                 or not isinstance(failure, Exception))):
                        cleanup = failure
            protected = pending is not None and (
                isinstance(pending, MemoryError) or not isinstance(pending, Exception))
            if cleanup is not None and not protected and (pending is None or (
                    isinstance(cleanup, MemoryError) or not isinstance(cleanup, Exception))):
                raise cleanup
