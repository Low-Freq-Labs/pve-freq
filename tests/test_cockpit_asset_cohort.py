"""Local fixed-asset checks; no server, credentials or provider operations."""
import hashlib
from pathlib import Path
import re
import unittest

from freq.modules import web_ui
from freq.services import standard_qemu_asset_policy as policy
from freq.services import standard_qemu_assets as assets


WEB = Path(__file__).resolve().parents[1] / 'freq' / 'data' / 'web'
REVISION = 'pve-lab-window-20261113-r1'
NEW_ASSETS = {'css/cockpit.css', 'css/cockpit-workspaces.css', 'js/cockpit-workspaces.js',
              'css/registered-lab-panel.css', 'js/registered-lab-panel.js', 'js/registered-lab-controller.js', 'css/lab-window-panel.css', 'js/lab-window-panel.js', 'js/lab-window-controller.js'}
APP_TARGETS = {
    '/', '/dashboard', '/dashboard/home', '/dashboard/fleet', '/dashboard/pve-firewall',
    '/dashboard/network', '/dashboard/storage', '/dashboard/docker', '/dashboard/security',
    '/dashboard/vault', '/dashboard/tools', '/dashboard/settings', '/dashboard/registered-lab',
}


class CockpitAssetCohortTests(unittest.TestCase):
    def test_exact_cohort_bytes_and_successful_original_local_acquisition(self):
        self.assertEqual(policy.SELECTED_ASSET_REVISION, REVISION)
        self.assertEqual(len(policy._ASSETS), 24)
        self.assertEqual(len({row[0] for row in policy._ASSETS}), 24)
        self.assertEqual(len({row[1] for row in policy._ASSETS}), 24)
        self.assertLessEqual(sum(row[3] for row in policy._ASSETS), 4 * 1024 * 1024)
        self.assertTrue(NEW_ASSETS.issubset({row[1] for row in policy._ASSETS}))
        for target, key, mime, size, digest in policy._ASSETS:
            with self.subTest(key=key):
                raw = (WEB / key).read_bytes()
                self.assertEqual(len(raw), size)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
                self.assertEqual(assets.get_asset('GET', target), (mime, raw, digest))
        attempt = assets._ATTEMPT
        self.assertEqual(len(attempt.streams), 24)
        self.assertEqual(attempt.close_stages, ['closed'] * 24)
        self.assertEqual(attempt.read_stages, ['returned'] * 24)
        self.assertTrue(all(stream.closed for stream in attempt.streams))

    def test_app_routes_exact_only_and_no_legacy_route_widening(self):
        self.assertEqual(set(policy._APP_TARGETS), APP_TARGETS)
        for target in APP_TARGETS:
            self.assertEqual(policy.select_asset('GET', target), policy._ASSETS[0][1:])
            self.assertIsNone(policy.select_asset('POST', target))
            self.assertIsNone(policy.select_asset('GET', target + '?v=' + REVISION))
        for target in ('/dashboard/media', '/dashboard/infra', '/dashboard/system',
                       '/dashboard/network/', '/dashboard/%6eetwork', '/dashboard/NETWORK'):
            self.assertIsNone(policy.select_asset('GET', target))

    def test_revision_edges_manifest_and_stale_asset_refusals(self):
        declared = {row[0] for row in policy._ASSETS}
        manifest = web_ui.FRONTEND_ASSET_MANIFEST
        self.assertTrue(NEW_ASSETS.issubset(manifest))
        self.assertEqual(len(manifest), len(set(manifest)))
        html = (WEB / 'app.html').read_text()
        edges = re.findall(r'(?:href|src)="(/static/[^\"]+)"', html)
        self.assertEqual(len(edges), 20)
        self.assertTrue(set(edges).issubset(declared))
        app = (WEB / 'js/app.js').read_text()
        for name in ('entry-decoder', 'observation-display'):
            target = '/static/js/cluster-observation/' + name + '.mjs?v=' + REVISION
            self.assertIn(target, app)
            self.assertIn(target, declared)
        display = (WEB / 'js/cluster-observation/observation-display.mjs').read_text()
        self.assertIn("'./observation-decoder.mjs?v=" + REVISION + "'", display)
        for target in declared - {'/'}:
            self.assertTrue(target.endswith('?v=' + REVISION))
            for rejected in (target.split('?')[0], target + '&extra=1',
                             target.replace(REVISION, 'pve-inventory-browse-20261113-r1'),
                             target.replace(REVISION, 'pve-cockpit-20261113-r1'),
                             target.replace(REVISION, 'pve-lab-cockpit-20261113-r1')):
                self.assertIsNone(policy.select_asset('GET', rejected))


if __name__ == '__main__':
    unittest.main()
