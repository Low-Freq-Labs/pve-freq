"""Original handler correlation across two requests; no sockets or config."""
import io
import json
import unittest
from unittest.mock import patch

from freq.modules import serve


class RequestCorrelation(unittest.TestCase):
    def test_reused_handler_sends_each_requests_own_correlation(self):
        handler = serve.FreqHandler.__new__(serve.FreqHandler)
        handler.path = '/api/pve/cluster-observation/inventory'
        handler.command = 'GET'
        handler.requestline = f'GET {handler.path} HTTP/1.1'
        handler.request_version = 'HTTP/1.1'
        handler.client_address = ('127.0.0.1', 0)
        handler.connection = object()
        handler.headers = {}
        handler.wfile = io.BytesIO()
        ids = []
        with patch.object(serve.logger, 'info'), patch.object(serve.logger, 'warn'):
            for _ in range(2):
                start = handler.wfile.tell()
                handler._begin_request()
                handler._json_response({'error': 'fixture-not-found'}, 404)
                response = handler.wfile.getvalue()[start:]
                head, raw = response.split(b'\r\n\r\n', 1)
                headers = dict(line.split(b': ', 1) for line in head.split(b'\r\n')[1:])
                body = json.loads(raw)
                self.assertRegex(body['request_id'], r'^[0-9a-f]{12}$')
                self.assertEqual(headers[b'X-Request-ID'].decode(), body['request_id'])
                self.assertEqual(int(headers[b'Content-Length']), len(raw))
                self.assertEqual(head.count(b'X-Request-ID:'), 1)
                ids.append(body['request_id'])
        self.assertNotEqual(*ids)


if __name__ == '__main__':
    unittest.main()
