"""Allow running as: python -m freq"""
import sys

# Version check before importing anything that uses dataclasses
from freq.core.compat import check_python
err = check_python()
if err:
    print(err, file=sys.stderr)
    sys.exit(1)

from freq.cli import main
sys.exit(main())
