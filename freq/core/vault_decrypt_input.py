"""Private Vault decryption caller metadata; no IO or secret values."""

from freq.core.vault_pipe_input import _VaultPipeReadDuty


class _VaultDecryptReadUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Required Vault decryption read is unavailable.')


class _VaultDecryptReadDuty:
    """One original lookup's whole-call receipt, never native closure proof."""
    __slots__ = ('lookup', 'key_read', 'directory', 'launch', 'job', 'cfg',
                 'setup_id', 'cred_key', 'used', 'request_stage', 'path_stage',
                 'candidate_path', 'helper_stage', 'exists_stage', 'exists_outcome',
                 'provider_stage', 'status_stage', 'status_outcome', 'decode_stage',
                 'outcome', 'caller_returned', 'raw_failure', 'ignored_failure',
                 'first_failures', 'failure', 'pipe_read')

    def __init__(self, lookup):
        self.lookup, self.key_read = lookup, lookup.key_read
        self.directory, self.launch = lookup.directory, lookup.launch
        self.job, self.cfg = lookup.job, lookup.cfg
        self.setup_id, self.cred_key = lookup.setup_id, 'bootstrap_password'
        self.used = self.caller_returned = False
        self.request_stage = self.path_stage = self.helper_stage = 'unused'
        self.exists_stage = self.exists_outcome = self.provider_stage = 'unused'
        self.status_stage = self.status_outcome = self.decode_stage = 'unused'
        self.outcome = 'unused'
        self.candidate_path = self.raw_failure = self.ignored_failure = None
        self.first_failures = [None] * 3
        self.failure = None
        self.pipe_read = None

    def remember(self, failure):
        self.raw_failure = failure
        if not issubclass(type(failure), Exception):
            kind = 0
        elif issubclass(type(failure), MemoryError):
            kind = 1
        else:
            kind = 2
        if self.first_failures[kind] is None:
            self.first_failures[kind] = failure
        for first in self.first_failures:
            if first is not None:
                self.failure = first
                break

    def refuse(self):
        first = self.failure
        if first is not None and (not issubclass(type(first), Exception)
                                  or issubclass(type(first), MemoryError)):
            raise first from None
        self.remember(_VaultDecryptReadUnavailable())
        raise self.failure from None

    def enter_request(self, key_read, cfg):
        try:
            if self.used:
                self.refuse()
            self.used = True
            self.request_stage = 'pending'
            lookup, directory, launch, job = (
                self.lookup, self.directory, self.launch, self.job)
            if (lookup.decrypt_read is not self or self.key_read is not key_read
                    or lookup.key_read is not key_read or key_read.lookup is not lookup
                    or key_read.directory is not directory
                    or key_read.launch is not launch or key_read.job is not job
                    or key_read.cfg is not cfg or not key_read.known()
                    or lookup.directory is not directory
                    or directory.bootstrap_lookup is not lookup
                    or lookup.launch is not launch or lookup.job is not job
                    or lookup.cfg is not cfg or self.cfg is not cfg
                    or directory.launch is not launch or directory.job is not job
                    or directory.cfg is not cfg or launch.job is not job
                    or job.get('_worker_launch') is not launch
                    or launch.preparation.directory is not directory
                    or launch.preparation.cfg is not cfg
                    or lookup.setup_id != self.setup_id
                    or not self.setup_id or job.get('setup_id') != self.setup_id
                    or lookup.cred_key != self.cred_key
                    or lookup.used is not True or lookup.stage != 'pending'
                    or lookup.failure is not None):
                self.refuse()
        except BaseException as failure:
            self.remember(failure)
            raise self.failure from None

    def enter_helper(self, path):
        if (self.used is not True or self.request_stage != 'pending'
                or self.path_stage != 'returned' or self.candidate_path is not path
                or self.helper_stage != 'unused' or self.failure is not None):
            self.refuse()
        self.helper_stage = 'pending'

    def known(self):
        if (self.used is not True or self.request_stage != 'pending'
                or self.path_stage != 'returned' or self.helper_stage != 'returned'
                or self.caller_returned is not True or self.failure is not None
                or self.exists_stage != 'returned'):
            return False
        if self.outcome == 'missing-policy-empty':
            return (self.exists_outcome == 'missing' and self.provider_stage == 'unused'
                    and self.status_stage == self.decode_stage == 'unused'
                    and self.ignored_failure is None)
        if self.exists_outcome != 'present':
            return False
        if self.outcome == 'caught-policy-empty':
            # The original ordinary-error policy returned empty. A pending
            # provider/decode stage remains unknown, not native closure.
            return self.ignored_failure is not None
        if (self.provider_stage != 'returned' or self.status_stage != 'returned'
                or self.ignored_failure is not None):
            return False
        if self.outcome == 'decoded':
            pipe = self.pipe_read
            return (self.status_outcome == 'zero' and self.decode_stage == 'returned'
                    and type(pipe) is _VaultPipeReadDuty and pipe.decrypt_read is self
                    and pipe.lookup is self.lookup and pipe.key_read is self.key_read
                    and pipe.directory is self.directory and pipe.launch is self.launch
                    and pipe.job is self.job and pipe.cfg is self.cfg and pipe.known())
        return (self.outcome == 'nonzero-policy-empty'
                and self.status_outcome == 'nonzero' and self.decode_stage == 'unused')
