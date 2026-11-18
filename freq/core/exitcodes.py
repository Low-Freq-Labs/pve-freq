"""FREQ exit codes — consistent return values across all commands.

Usage:
    from freq.core.exitcodes import SUCCESS, PARTIAL_FAILURE, CONFIG_ERROR
    return SUCCESS

Codes follow POSIX conventions (0 = success, non-zero = failure)
with domain-specific granularity for scripting and CI integration.
"""

SUCCESS = 0              # All operations completed successfully
PARTIAL_FAILURE = 1      # Some operations failed, some succeeded
TOTAL_FAILURE = 2        # All operations failed
CONFIG_ERROR = 3         # Configuration invalid or missing
CONNECTIVITY_ERROR = 4   # Cannot reach any target hosts
