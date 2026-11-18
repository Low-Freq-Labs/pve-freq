"""Fixed selected Cluster pilot routing DATA; no admission, IO or service.

Derived from exact independently source-reviewed frontend asset manifest.
Only fixed Home/Fleet/Firewall reloads and12 selected URLs are classified, never generic
SPA/static prefixes or request-supplied cache flags. The enclosing original
startup/dispatcher must bind actual served bytes, original auth/CSRF/cohort,
currentness and once-response custody. A returned tuple grants no authority.
"""
SELECTED_ASSET_REVISION = 'original-guest-workspace-20261024-r50'

_ROUTES = (
    ('GET', '/', 'app', 'app.html'),
    ('GET', '/dashboard', 'app', 'app.html'),
    ('GET', '/dashboard/home', 'app', 'app.html'),
    ('GET', '/dashboard/fleet', 'app', 'app.html'),
    ('GET', '/dashboard/pve-firewall', 'app', 'app.html'),
    ('POST', '/api/auth/login', 'login', None),
    ('GET', '/api/auth/verify', 'verify', None),
    ('POST', '/api/auth/logout', 'logout', None),
    ('GET', '/api/exec/targets', 'fleet-targets', None),
    ('GET', '/api/pve/cluster-observation/inventory', 'inventory', None),
    ('POST', '/api/pve/cluster-observation/bind', 'bind', None),
    ('POST', '/api/pve/cluster-observation/read', 'read', None),
    ('GET', '/api/guest-read/v1/sources', 'guest-sources', None),
    ('POST', '/api/guest-read/v1/inventory', 'guest-inventory', None),
    ('POST', '/api/guest-read/v1/profile', 'guest-profile', None),
    ('POST', '/api/guest-read/v2/open', 'guest-owner-open', None),
    ('POST', '/api/guest-read/v2/sources', 'guest-owner-sources', None),
    ('POST', '/api/guest-read/v2/inventory', 'guest-owner-inventory', None),
    ('POST', '/api/guest-read/v2/profile', 'guest-owner-profile', None),
    ('POST', '/api/guest-read/v2/retire', 'guest-owner-retire', None),
    ('GET', '/static/css/app.css?v=original-guest-workspace-20261024-r50', 'asset', 'css/app.css'),
    ('GET', '/static/vendor/xterm/xterm.min.css?v=original-guest-workspace-20261024-r50', 'asset', 'vendor/xterm/xterm.min.css'),
    ('GET', '/static/vendor/xterm/xterm.min.js?v=original-guest-workspace-20261024-r50', 'asset', 'vendor/xterm/xterm.min.js'),
    ('GET', '/static/vendor/xterm/addon-fit.min.js?v=original-guest-workspace-20261024-r50', 'asset', 'vendor/xterm/addon-fit.min.js'),
    ('GET', '/static/vendor/xterm/addon-clipboard.min.js?v=original-guest-workspace-20261024-r50', 'asset', 'vendor/xterm/addon-clipboard.min.js'),
    ('GET', '/static/js/router.js?v=original-guest-workspace-20261024-r50', 'asset', 'js/router.js'),
    ('GET', '/static/js/presentation.js?v=original-guest-workspace-20261024-r50', 'asset', 'js/presentation.js'),
    ('GET', '/static/js/quick-ct.js?v=original-guest-workspace-20261024-r50', 'asset', 'js/quick-ct.js'),
    ('GET', '/static/js/app.js?v=original-guest-workspace-20261024-r50', 'asset', 'js/app.js'),
    ('GET', '/static/js/cluster-observation/entry-decoder.mjs?v=original-guest-workspace-20261024-r50', 'asset', 'js/cluster-observation/entry-decoder.mjs'),
    ('GET', '/static/js/cluster-observation/observation-display.mjs?v=original-guest-workspace-20261024-r50', 'asset', 'js/cluster-observation/observation-display.mjs'),
    ('GET', '/static/js/cluster-observation/observation-decoder.mjs?v=original-guest-workspace-20261024-r50', 'asset', 'js/cluster-observation/observation-decoder.mjs'),
)


def classify_request(method, target):
    """Return a fixed routing tuple or None. Never normalize or dispatch.

    Read the original bounded request method/target once in the enclosing
    owner. Unknowns, encoded aliases, extra query members and alternate methods
    never fall through to a generic SPA/API/static prefix route.
    """
    if type(method) is not str or type(target) is not str:
        return None
    if method not in ('GET', 'POST') or not 0 < len(target) <= 1024:
        return None
    for expected_method, expected_target, operation, asset in _ROUTES:
        if method == expected_method and target == expected_target:
            return operation, asset
    return None
