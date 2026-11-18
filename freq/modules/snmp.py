"""Compatibility alias for the downward-owned SNMP implementation.

Domain: freq net snmp <action> [target]
Replaces: legacy SNMP ownership at this upward module path.
"""

import sys

from freq.services import snmp as _snmp

sys.modules[__name__] = _snmp
