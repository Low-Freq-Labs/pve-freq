"""Compatibility alias for the downward-owned credential vault.

The implementation lives in :mod:`freq.core.vault`.  Alias the module object
instead of copying names so legacy private monkeypatches and CLI imports keep
operating on the implementation's actual globals.
"""

import sys

from freq.core import vault as _vault

sys.modules[__name__] = _vault
