"""Exact read-only dashboard frontend asset policy DATA only.

No IO, source/root/session/installation/admission or response authority.
The original serving join must select these exact complete cohort bytes,
without generic path/query normalization, old revision or mixed fallback.
Historical pilot/nativeFalse/CLI78 policies are separate and unchanged.
"""

SELECTED_ASSET_REVISION = 'pve-lab-window-20261113-r1'
# (exact original URL, package-relative key, MIME, exact bytes, SHA256)
_ASSETS = (
    ('/', 'app.html', 'text/html', 117606, '4efce925747fd4d57a5ae6a1e675f8439c3c79d5c57902eab923e3e166e7891d'),
    ('/static/css/app.css?v=pve-lab-window-20261113-r1', 'css/app.css', 'text/css', 121952, '2b8ddd56072ba13e1e6d8d0973b68d2f24588598f9cf2c8793a4aad4d89c41c4'),
    ('/static/vendor/xterm/xterm.min.css?v=pve-lab-window-20261113-r1', 'vendor/xterm/xterm.min.css', 'text/css', 2657, 'b3dee1c4fd6401160a95d726d6532fc72c8e38f2392b66d552a88aa22cb23e12'),
    ('/static/vendor/xterm/xterm.min.js?v=pve-lab-window-20261113-r1', 'vendor/xterm/xterm.min.js', 'application/javascript', 289557, 'c396d1fb827e8dbd0df413b1aff16f3cc662c480924c7a1831a2d20b9a2d3098'),
    ('/static/vendor/xterm/addon-fit.min.js?v=pve-lab-window-20261113-r1', 'vendor/xterm/addon-fit.min.js', 'application/javascript', 1618, 'c22de0e0e65f0ba77ca6c341c984b5da549ed56c18fcb080b38d201692bfec47'),
    ('/static/vendor/xterm/addon-clipboard.min.js?v=pve-lab-window-20261113-r1', 'vendor/xterm/addon-clipboard.min.js', 'application/javascript', 6476, '243df279a2c09c1251b4fc70447200d66dc30e6b28ef33fb85531a3d94eec755'),
    ('/static/js/router.js?v=pve-lab-window-20261113-r1', 'js/router.js', 'application/javascript', 5169, '34dd5a4310089dcd5614e141fe42086585b7a9c72975774db081bfe393582e90'),
    ('/static/js/presentation.js?v=pve-lab-window-20261113-r1', 'js/presentation.js', 'application/javascript', 2324, '38236c70a38d16b8579ca91c366a5539a29f2b8c138beb81159de88e4e84d66e'),
    ('/static/js/quick-ct.js?v=pve-lab-window-20261113-r1', 'js/quick-ct.js', 'application/javascript', 13411, '24c458c36a654b9e3360889da26dc30ecb85a6aaaa2459b1dc7a859ab0669f67'),
    ('/static/js/app.js?v=pve-lab-window-20261113-r1', 'js/app.js', 'application/javascript', 2757486, '23065719099ff82dfbae7c2df17cb7ac750a67b217399940b17d2f907e2e99e3'),
    ('/static/js/cluster-observation/entry-decoder.mjs?v=pve-lab-window-20261113-r1', 'js/cluster-observation/entry-decoder.mjs', 'application/javascript', 5104, '87fbaf72906333a52c5fef4955580bc6ffd1b71dd0fa03795d548659e2b8d37c'),
    ('/static/js/cluster-observation/observation-display.mjs?v=pve-lab-window-20261113-r1', 'js/cluster-observation/observation-display.mjs', 'application/javascript', 12957, '2d016a7360b24464089fbaed80ed9292905cb182374d692680932af9d467f991'),
    ('/static/js/cluster-observation/observation-decoder.mjs?v=pve-lab-window-20261113-r1', 'js/cluster-observation/observation-decoder.mjs', 'application/javascript', 8832, 'ace8e2922980242b8de84bb305a36ed3c386e516dc56f47905a74ba2d5cc6b0f'),
    ('/static/js/pve-inventory.js?v=pve-lab-window-20261113-r1', 'js/pve-inventory.js', 'application/javascript', 21891, '53c8c7b086b401e2bace58cad6fb99b9dd5b013d4a01ddc5a73723cbe58aa40b'),
    ('/static/js/pve-source-config.js?v=pve-lab-window-20261113-r1', 'js/pve-source-config.js', 'application/javascript', 9035, '84a8f151f2cf08c5db580e91d115b11dc8c78001ff976b9ce9518c633c2a7cdd'),
    ('/static/css/cockpit.css?v=pve-lab-window-20261113-r1', 'css/cockpit.css', 'text/css', 7782, '8d54d112f44ff60681ccf48facc81351574e211210d856744ae325f97437e638'),
    ('/static/css/cockpit-workspaces.css?v=pve-lab-window-20261113-r1', 'css/cockpit-workspaces.css', 'text/css', 9840, 'eba63cbd5c0bdb6c257dbef4c6d736cd5a0bb7dd5ac2a5a092508020f77bcf19'),
    ('/static/js/cockpit-workspaces.js?v=pve-lab-window-20261113-r1', 'js/cockpit-workspaces.js', 'application/javascript', 18140, '2219ffd08ce8929f44e794d38736bfdaa608357497872c16b1eeb6c9025cf7e5'),
    ('/static/css/registered-lab-panel.css?v=pve-lab-window-20261113-r1', 'css/registered-lab-panel.css', 'text/css', 4747, '859119372e0827a34c862b063cc87b4e61ca1b7a1a2d1df0c21ac7e48f2c79f4'),
    ('/static/js/registered-lab-panel.js?v=pve-lab-window-20261113-r1', 'js/registered-lab-panel.js', 'application/javascript', 10429, 'a56ff1d70d6b39b92abface2f3c920c74f55b0770f7236c8e8a9eb274f1f8f0c'),
    ('/static/js/registered-lab-controller.js?v=pve-lab-window-20261113-r1', 'js/registered-lab-controller.js', 'application/javascript', 21627, '3250fb4ca2948cee59dd32d97d2466e90f136ac5fcb193e41c06a5a2ff793ecb'),
    ('/static/css/lab-window-panel.css?v=pve-lab-window-20261113-r1', 'css/lab-window-panel.css', 'text/css', 3643, 'fa9117a03cc3e8f1d1905b02fc079fb3f951c452515313f80a4509215e194b9b'),
    ('/static/js/lab-window-panel.js?v=pve-lab-window-20261113-r1', 'js/lab-window-panel.js', 'application/javascript', 17269, '5f409a6ef9094e6203b2c7b9d674bce5bd7f2ce36ec4e050702c735d3b656451'),
    ('/static/js/lab-window-controller.js?v=pve-lab-window-20261113-r1', 'js/lab-window-controller.js', 'application/javascript', 21332, '63af4bdacdddad7a0329f59a001eff0967f2de684b8d4605f1cb4c1ff82856e9'),
)

_APP_TARGETS = ('/', '/dashboard', '/dashboard/home', '/dashboard/fleet',
                '/dashboard/pve-firewall', '/dashboard/network', '/dashboard/storage',
                '/dashboard/docker', '/dashboard/security', '/dashboard/vault',
                '/dashboard/tools', '/dashboard/settings', '/dashboard/registered-lab')


def select_asset(method, target):
    """Return fixed key/MIME/size/digest DATA or None, never acquire/dispatch.

    The original owner reads a bounded raw target once. Unknown, encoded,
    extra-query, alternate method and stale revision values never normalize
    into this cohort. Matching DATA is not provenance or a serving grant.
    """
    if type(method) is not str or type(target) is not str:
        return None
    if method != 'GET' or not 0 < len(target) <= 1024:
        return None
    if target in _APP_TARGETS:
        return _ASSETS[0][1:]
    for expected, key, mime, size, digest in _ASSETS[1:]:
        if target == expected:
            return key, mime, size, digest
    return None
