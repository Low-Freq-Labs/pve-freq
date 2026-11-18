"""Compatibility alias for downward-owned certificate lifecycle management.

Domain: freq cert <acme|ca|inspect|deploy> <action>
Replaces: legacy certificate lifecycle ownership at this upward module path.
"""

import sys

from freq.services import cert_management as _cert_management

sys.modules[__name__] = _cert_management
