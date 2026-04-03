"""Built-in policies for FREQ engine.

Each policy is a declarative dict — data, not code.
Add new policies by creating a module with a POLICY dict.
"""

from freq.engine.policies.ssh_hardening import POLICY as SSH_HARDENING
from freq.engine.policies.ntp_sync import POLICY as NTP_SYNC
from freq.engine.policies.rpcbind import POLICY as RPCBIND

ALL_POLICIES = [SSH_HARDENING, NTP_SYNC, RPCBIND]
