"""Read-only inventory behavior with fictional rows and no provider traffic."""

import datetime
import json
import ssl
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from freq.services import pve_read_inventory as inventory


def _cfg(*sources):
    return SimpleNamespace(pve_nodes=list(sources), pve_api_verify_ssl=False,
                           pve_api_ca_file="")


def _resolve(rows, *, cfg=None):
    return inventory.resolve_inventory(
        cfg or _cfg("192.0.2.10"), fetch=lambda *_args: rows, now=lambda: 100.0
    )


def test_failed_first_source_keeps_later_independent_success_and_no_error_details():
    calls = []

    def fetch(cfg, source, timeout):
        calls.append((source, timeout))
        if source == "192.0.2.10":
            raise OSError("private-token-and-provider-body")
        return [{"type": "node", "node": "second"},
                {"type": "qemu", "node": "second", "vmid": 101}]

    result = inventory.resolve_inventory(
        _cfg("192.0.2.10", "192.0.2.11"), fetch=fetch, now=lambda: 100.0
    )
    assert result["schema"] == 1
    assert result["read_only"] is True
    assert datetime.datetime.fromisoformat(result["observed_at"]).utcoffset() == datetime.timedelta(0)
    assert result["state"] == "partial"
    assert calls == [("192.0.2.10", inventory.SOURCE_TIMEOUT),
                     ("192.0.2.11", inventory.SOURCE_TIMEOUT)]
    failed, successful = result["sources"]
    assert failed == {"source": "192.0.2.10", "state": "unavailable",
                      "error": "provider_unavailable", "nodes": [], "guests": []}
    assert successful["state"] == "ok"
    assert successful["error"] is None
    assert successful["nodes"][0]["node"] == "second"
    assert successful["guests"][0]["vmid"] == 101
    assert "private-token-and-provider-body" not in json.dumps(result)


def test_same_guest_vmid_and_name_are_preserved_per_source():
    result = _resolve(
        [{"type": "qemu", "node": "pve", "vmid": 101, "name": "same-name"}],
        cfg=_cfg("192.0.2.10", "192.0.2.11"),
    )
    assert result["state"] == "ok"
    assert [row["source"] for row in result["sources"]] == ["192.0.2.10", "192.0.2.11"]
    assert [row["guests"][0]["vmid"] for row in result["sources"]] == [101, 101]


def test_valid_guest_and_node_metrics_are_projected_without_coercion():
    result = _resolve([
        {"type": "node", "node": "pve", "status": "online", "cpu": 0.25,
         "mem": 100, "maxmem": 200, "disk": 300, "maxdisk": 400, "uptime": 500},
        {"type": "qemu", "node": "pve", "vmid": 101, "name": "guest",
         "status": "stopped", "cpu": 0, "mem": 0, "maxmem": 200,
         "maxcpu": 2, "disk": 0, "maxdisk": 400, "uptime": 0},
    ])
    assert result["state"] == "ok"
    source = result["sources"][0]
    assert source["nodes"][0]["cpu"] == 0.25
    assert source["nodes"][0]["maxdisk"] == 400
    guest = source["guests"][0]
    assert (guest["status"], guest["mem"], guest["disk"], guest["uptime"]) == ("stopped", 0, 0, 0)
    assert guest["template"] is None


def test_empty_success_differs_from_provider_failure_and_no_configuration():
    empty = _resolve([])
    assert empty["state"] == "ok"
    assert empty["sources"] == [{"source": "192.0.2.10", "state": "ok",
                                  "error": None, "nodes": [], "guests": []}]
    failing_fetch = Mock(side_effect=RuntimeError("private"))
    failed = inventory.resolve_inventory(_cfg("192.0.2.10"), fetch=failing_fetch)
    assert failed["state"] == "unavailable"
    assert failed["sources"][0]["error"] == "provider_unavailable"
    unused_fetch = Mock(side_effect=AssertionError("must not fetch"))
    unconfigured = inventory.resolve_inventory(_cfg(), fetch=unused_fetch)
    assert unconfigured["state"] == "unconfigured"
    assert unconfigured["sources"] == []
    unused_fetch.assert_not_called()


def test_missing_fields_stay_null_and_unknown_resource_families_are_omitted():
    result = _resolve([{"type": "node", "node": "pve"}, {"type": "lxc", "node": "pve", "vmid": 101},
                       {"type": "storage", "password": "discard"}])
    source = result["sources"][0]
    assert result["state"] == "ok"
    assert source["nodes"] == [{"node": "pve", **{field: None for field in
                                ("name", "status", "cpu", "mem", "maxmem", "disk", "maxdisk", "uptime")}}]
    assert source["guests"] == [{"type": "lxc", "node": "pve", "vmid": 101, **{field: None for field in
        ("name", "status", "template", "cpu", "mem", "maxmem", "maxcpu", "disk", "maxdisk", "uptime")}}]
    assert "password" not in json.dumps(result)


@pytest.mark.parametrize("value,expected", [(None, None), (False, False), (True, True), (0, False), (1, True)])
def test_template_uses_only_explicit_flag_even_for_high_vmid(value, expected):
    row = {"type": "qemu", "node": "pve", "vmid": 9000}
    if value is not None:
        row["template"] = value
    result = _resolve([row])
    assert result["state"] == "ok"
    assert result["sources"][0]["guests"][0]["template"] is expected


@pytest.mark.parametrize("rows", [
    None, {}, "[]", [None],
    [{"type": "node", "name": []}],
    [{"type": "qemu", "vmid": True}],
    [{"type": "qemu", "vmid": 101.0}],
    [{"type": "qemu", "template": "yes"}],
    [{"type": "qemu", "cpu": float("nan")}],
    [{"type": "qemu", "cpu": float("inf")}],
    [{"type": "node", "mem": -1}],
    [{"type": "node", "name": "bad\nname"}],
])
def test_invalid_known_rows_refuse_entire_source_without_partial_payload(rows):
    if isinstance(rows, list):
        rows = [{"node": "other", "vmid": 102, **row} if isinstance(row, dict) else row for row in rows]
        rows = [{"type": "qemu", "node": "pve", "vmid": 101}] + rows
    result = _resolve(rows)
    assert result["state"] == "unavailable"
    assert result["sources"][0] == {
        "source": "192.0.2.10", "state": "unavailable", "error": "invalid_response",
        "nodes": [], "guests": [],
    }


@pytest.mark.parametrize("rows", [
    [{"type": "node"}], [{"type": "node", "node": "   "}],
    [{"type": "qemu", "node": "pve"}],
    [{"type": "qemu", "node": "pve", "vmid": 0}],
    [{"type": "qemu", "node": "pve", "vmid": 101, "mem": 2**53}],
    [{"type": "node", "node": "pve"}] * 2,
    [{"type": "qemu", "node": "pve", "vmid": 101}] * 2,
])
def test_missing_identity_unsafe_numbers_and_duplicate_rows_are_unavailable(rows):
    result = _resolve(rows)
    assert result["state"] == "unavailable"
    assert result["sources"][0]["error"] == "invalid_response"
    assert result["sources"][0]["nodes"] == result["sources"][0]["guests"] == []


@pytest.mark.parametrize("sources", ["192.0.2.10", ["https://192.0.2.10"],
                                     ["192.0.2.10", "192.0.2.10"],
                                     ["192.0.2.10"] * (inventory.MAX_SOURCES + 1)])
def test_invalid_or_over_limit_configuration_does_not_fetch(sources):
    cfg = _cfg()
    cfg.pve_nodes = sources
    fetch = Mock(side_effect=AssertionError("must not fetch"))
    result = inventory.resolve_inventory(cfg, fetch=fetch)
    assert result["state"] == "unavailable"
    assert result["sources"] == []
    fetch.assert_not_called()


def test_total_deadline_does_not_restart_for_later_sources():
    instant = [100.0]
    calls = []

    def fetch(cfg, source, timeout):
        calls.append(source)
        instant[0] += inventory.TOTAL_TIMEOUT + 1
        return []

    result = inventory.resolve_inventory(
        _cfg("192.0.2.10", "192.0.2.11"), fetch=fetch, now=lambda: instant[0]
    )
    assert result["state"] == "unavailable"
    assert calls == ["192.0.2.10"]
    assert all(source["error"] == "provider_unavailable" for source in result["sources"])


def test_memory_exhaustion_is_not_rewritten_as_provider_unavailable():
    error = MemoryError("synthetic")
    with pytest.raises(MemoryError) as raised:
        inventory.resolve_inventory(_cfg("192.0.2.10"), fetch=Mock(side_effect=error))
    assert raised.value is error


def _transport(monkeypatch, *, payload=b'{"data":[]}', status=200, headers=None,
               request_error=None):
    response = Mock(status=status)
    response.getheader.side_effect = lambda name, default=None: (headers or {}).get(name, default)
    remaining = [payload]

    def read(size):
        chunk, remaining[0] = remaining[0][:size], remaining[0][size:]
        return chunk

    response.read1.side_effect = read
    response.isclosed.return_value = False
    connection = Mock()
    connection.getresponse.return_value = response
    if request_error is not None:
        connection.request.side_effect = request_error
    constructor = Mock(return_value=connection)
    context = SimpleNamespace(check_hostname=True, verify_mode=ssl.CERT_REQUIRED)
    context_factory = Mock(return_value=context)
    monkeypatch.setattr(inventory.http.client, "HTTPSConnection", constructor)
    monkeypatch.setattr(inventory.ssl, "create_default_context", context_factory)
    monkeypatch.setattr(inventory, "_pve_api_credentials", lambda *_args: ("reader@pve!demo", "fictional-secret"))
    return connection, response, constructor, context_factory, context


def test_transport_uses_verified_tls_fixed_get_and_closes_connection(monkeypatch):
    connection, response, constructor, factory, context = _transport(monkeypatch)
    cfg = _cfg("192.0.2.10")
    cfg.pve_api_ca_file = "/fictional/ca.pem"
    result = inventory.resolve_inventory(cfg, now=lambda: 100.0)
    assert result["state"] == "ok"
    factory.assert_called_once_with(cafile="/fictional/ca.pem")
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    constructor.assert_called_once_with("192.0.2.10", 8006, timeout=inventory.SOURCE_TIMEOUT, context=context)
    connection.request.assert_called_once_with("GET", "/api2/json/cluster/resources", headers={
        "Authorization": "PVEAPIToken=reader@pve!demo=fictional-secret",
        "Accept": "application/json", "Accept-Encoding": "identity",
    })
    assert all(0 < call.args[0] <= 65536 for call in response.read1.call_args_list)
    connection.close.assert_called_once_with()
    assert "fictional-secret" not in json.dumps(result)


@pytest.mark.parametrize("status", [301, 302, 307, 401, 403, 500])
def test_transport_never_follows_redirect_or_retries(monkeypatch, status):
    connection, response, constructor, *_rest = _transport(
        monkeypatch, status=status, headers={"Location": "https://other.invalid/secret"}
    )
    result = inventory.resolve_inventory(_cfg("192.0.2.10"), now=lambda: 100.0)
    assert result["sources"][0]["error"] == "provider_unavailable"
    assert constructor.call_count == connection.request.call_count == 1
    response.read1.assert_not_called()
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("payload,headers", [
    (b'{"data":[]}', {"Content-Length": str(inventory.MAX_BODY + 1)}),
    (b'{"data":[]}', {"Content-Encoding": "gzip"}),
    (b'{"data":[]}', {"Content-Length": "99"}),
    (b"x" * (inventory.MAX_BODY + 1), {}),
    (b'{"data":[],"data":[]}', {}),
    (b'{"unexpected":[]}', {}),
    (b'[]', {}),
    (b'not-json-private-body', {}),
])
def test_transport_bounds_and_invalid_documents_refuse_and_close(monkeypatch, payload, headers):
    connection, *_rest = _transport(monkeypatch, payload=payload, headers=headers)
    result = inventory.resolve_inventory(_cfg("192.0.2.10"), now=lambda: 100.0)
    assert result["sources"][0]["error"] == "invalid_response"
    assert result["sources"][0]["nodes"] == result["sources"][0]["guests"] == []
    assert "private-body" not in json.dumps(result)
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("error,code", [(ssl.SSLError("private-token"), "tls_unavailable"),
                                        (OSError("private-token"), "provider_unavailable")])
def test_transport_errors_are_fixed_public_codes_and_close(monkeypatch, error, code):
    connection, *_rest = _transport(monkeypatch, request_error=error)
    result = inventory.resolve_inventory(_cfg("192.0.2.10"), now=lambda: 100.0)
    assert result["sources"][0]["error"] == code
    assert "private-token" not in json.dumps(result)
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("credentials", [("", "secret"), ("reader", ""),
                                          ("reader", "secret\nheader"), (None, "secret")])
def test_invalid_credentials_do_not_open_provider_connection(monkeypatch, credentials):
    _connection, _response, constructor, *_rest = _transport(monkeypatch)
    monkeypatch.setattr(inventory, "_pve_api_credentials", lambda *_args: credentials)
    result = inventory.resolve_inventory(_cfg("192.0.2.10"), now=lambda: 100.0)
    assert result["sources"][0]["error"] == "credentials_unavailable"
    constructor.assert_not_called()


def test_unavailable_ca_never_weakens_tls_or_opens_connection(monkeypatch):
    _connection, _response, constructor, factory, _context = _transport(monkeypatch)
    factory.side_effect = OSError("private-ca-path")
    result = inventory.resolve_inventory(_cfg("192.0.2.10"), now=lambda: 100.0)
    assert result["sources"][0]["error"] == "tls_unavailable"
    assert "private-ca-path" not in json.dumps(result)
    constructor.assert_not_called()
