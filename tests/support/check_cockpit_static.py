"""Read exact frontend bytes through an explicit normal HTTPS origin."""
import argparse
import datetime
import hashlib
import http.client
import json
from pathlib import Path
import ssl
from urllib.parse import urlsplit

from freq.services import standard_qemu_asset_policy as policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--evidence', required=True, type=Path)
    args = parser.parse_args()
    target = urlsplit(args.origin)
    if (target.scheme != 'https' or not target.hostname or target.username or
            target.password or target.path not in ('', '/') or target.query or target.fragment):
        parser.error('An explicit HTTPS origin without credentials, query or fragment is required')
    if not args.evidence.is_absolute() or args.evidence.exists():
        parser.error('Evidence must be a new absolute file')
    receipt = {'schema': 1, 'origin': args.origin,
               'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'asset_revision': policy.SELECTED_ASSET_REVISION,
               'scope': 'Normal DNS and strict TLS, read-only exact HTTP GET bytes; no redirects, credentials or provider requests.',
               'passed': False, 'assets': []}
    for path, key, mime, size, digest in policy._ASSETS:
        item = {'target': path, 'key': key, 'passed': False}
        connection = http.client.HTTPSConnection(target.hostname, target.port or 443,
                                                 timeout=10, context=ssl.create_default_context())
        try:
            connection.request('GET', path, headers={'Accept': mime})
            response = connection.getresponse()
            item['status'] = response.status
            item['content_type'] = response.getheader('Content-Type', '').split(';', 1)[0].strip()
            if response.status == 200:
                body = response.read(size + 1)
                item.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
                item['passed'] = len(body) == size and item['sha256'] == digest and item['content_type'] == mime
        except Exception as error:
            item['failure_class'] = type(error).__name__
        finally:
            connection.close()
        receipt['assets'].append(item)
    receipt['passed'] = all(row['passed'] for row in receipt['assets'])
    with args.evidence.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'passed': receipt['passed'], 'assets': len(receipt['assets']),
                      'evidence': str(args.evidence)}))
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
