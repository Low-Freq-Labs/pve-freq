"""Actual TLS framing witnesses for the explicit offline fixture only.

Invoked by a reviewed remote entry with an already owned fixture server.
This module never starts a server or contacts a configured provider.
"""
import json
import hashlib
import socket
import ssl
import time


def exchange(port, method, path, body=b'', extra=(), *, partial=False):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('fixture port')
    context = ssl._create_unverified_context()
    headers = [
        f'{method} {path} HTTP/1.1', f'Host: 127.0.0.1:{port}',
        'Cookie: freq_session=offline-cluster-fixture-session',
        'X-Freq-CSRF: offline-cluster-fixture-csrf',
        f'Origin: https://127.0.0.1:{port}', 'Connection: close',
    ]
    if method == 'POST':
        headers += ['Content-Type: application/json', f'Content-Length: {len(body)}']
    headers.extend(extra)
    request = ('\r\n'.join(headers) + '\r\n\r\n').encode('ascii')
    start = time.monotonic()
    deadline = start + 12
    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError('total fixture exchange deadline')
        return value
    with socket.create_connection(('127.0.0.1', port), timeout=remaining()) as raw:
        raw.settimeout(remaining())
        with context.wrap_socket(raw, server_hostname='localhost') as connection:
            connection.settimeout(remaining())
            connection.sendall(request + (body[:1] if partial else body))
            chunks, size = [], 0
            while True:
                connection.settimeout(remaining())
                piece = connection.recv(65536)
                if not piece:
                    break
                size += len(piece)
                if size > 2 * 1024 * 1024 + 16384:
                    raise AssertionError('response wire bound')
                chunks.append(piece)
    return b''.join(chunks), time.monotonic() - start


def decode(wire, expected):
    headers, separator, body = wire.partition(b'\r\n\r\n')
    assert separator and headers.split(b'\r\n', 1)[0].split()[1] == str(expected).encode()
    assert wire.count(b'HTTP/1.') == 1
    lengths = [line.split(b':', 1)[1].strip() for line in headers.split(b'\r\n')[1:]
               if line.lower().startswith(b'content-length:')]
    assert len(lengths) == 1 and int(lengths[0]) == len(body)
    return json.loads(body)


def fresh_binding(port):
    wire, _ = exchange(port, 'GET', '/api/fleet/overview')
    inventory = decode(wire, 200)
    selection = inventory['pve_nodes'][0]['cluster_report_selection_ref']
    wire, _ = exchange(port, 'POST', '/api/pve/cluster-report/bind',
                       json.dumps({'selection_ref': selection}).encode())
    return decode(wire, 200)['binding_ref']


def run(port):
    results = []
    for name in ('duplicate_content_length', 'transfer_encoding_and_length', 'partial_body_deadline'):
        binding = fresh_binding(port)
        body = json.dumps({'binding_ref': binding}).encode()
        extra = ((f'Content-Length: {len(body)}',) if name == 'duplicate_content_length'
                 else ('Transfer-Encoding: chunked',) if name == 'transfer_encoding_and_length' else ())
        wire, elapsed = exchange(port, 'POST', '/api/pve/cluster-report/read', body, extra,
                                 partial=name == 'partial_body_deadline')
        if name == 'partial_body_deadline':
            assert wire == b'' and 9 <= elapsed < 12, (wire[:100], elapsed)
        else:
            assert decode(wire, 400) == {'error': 'cluster_report_unavailable'}
        # An invalid framing attempt must not consume the original binding.
        good, _ = exchange(port, 'POST', '/api/pve/cluster-report/read', body)
        public = decode(good, 200)
        assert public['schema'] == 'cluster-status-browser-v1'
        assert public['profile'] == 'pve-cluster-status-supplied-v1'
        assert public['state'] == 'supplied_rows'
        assert [node['name'] for node in public['nodes']] == ['fixture-node']
        spent, _ = exchange(port, 'POST', '/api/pve/cluster-report/read', body)
        assert decode(spent, 409) == {'error': 'cluster_report_unavailable'}
        results.append({'case': name, 'passed': True, 'elapsed_seconds': elapsed,
                        'refused_wire_bytes': len(wire), 'original_binding_reused_once': True,
                        'wire_evidence': [{'phase': phase, 'bytes': len(data),
                                           'sha256': hashlib.sha256(data).hexdigest(),
                                           'status_line': data.split(b'\r\n', 1)[0].decode('ascii')}
                                          for phase, data in (('refusal', wire), ('success', good), ('reuse', spent))],
                        'public_identity': {'schema': public['schema'], 'profile': public['profile'],
                                            'state': public['state'], 'node_names': ['fixture-node']}})
    return results


def run_partial_write(server):
    """Requires a separate positive fixture with wire_fault='body_prefix'."""
    binding = fresh_binding(server.server_port)
    body = json.dumps({'binding_ref': binding}).encode()
    wire, elapsed = exchange(server.server_port, 'POST', '/api/pve/cluster-report/read', body)
    headers, separator, prefix = wire.partition(b'\r\n\r\n')
    assert separator and headers.split(b'\r\n', 1)[0].split()[1] == b'200'
    assert wire.count(b'HTTP/1.') == 1
    assert len(prefix) == 8 and prefix == server.fixture_prefix_sent
    declared = [int(line.split(b':', 1)[1]) for line in headers.split(b'\r\n')[1:]
                if line.lower().startswith(b'content-length:')]
    assert len(declared) == 1 and declared[0] > len(prefix)
    again, _ = exchange(server.server_port, 'POST', '/api/pve/cluster-report/read', body)
    assert decode(again, 409) == {'error': 'cluster_report_unavailable'}
    return {'case': 'real_body_prefix_failure', 'passed': True, 'elapsed_seconds': elapsed,
            'declared_bytes': declared[0], 'received_body_bytes': len(prefix),
            'wire_sha256': hashlib.sha256(wire).hexdigest(), 'prefix_hex': prefix.hex(),
            'second_status_absent': True, 'binding_consumed': True}
