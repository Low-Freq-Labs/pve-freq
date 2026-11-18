"""Compatibility alias for the downward-owned PVE domain implementation.

The implementation lives in :mod:`freq.services.pve`. Alias the module object
instead of copying names so legacy private monkeypatches and CLI imports keep
operating on the implementation's actual globals.
"""

import sys

from freq.services import pve as _pve

sys.modules[__name__] = _pve
