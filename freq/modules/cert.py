"""Compatibility alias for the downward-owned certificate inventory."""

import sys

from freq.services import cert as _cert

sys.modules[__name__] = _cert
