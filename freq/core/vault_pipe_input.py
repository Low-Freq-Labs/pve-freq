"""Draft original pipe-call observations; no IO, providers or secret values."""

from freq.core.vault_child_input import _VaultChildReadDuty


class _VaultPipeReadUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Required Vault pipe acquisition is unavailable.')


class _VaultPipeReadDuty:
    """Prepublished process-local pair/once-close metadata, no native identity."""
    __slots__ = ('decrypt_read', 'lookup', 'key_read', 'directory', 'launch',
                 'job', 'cfg', 'setup_id', 'used', 'stage', 'pair_stage', 'pair',
                 'unpack_stage', 'read_fd', 'write_fd', 'payload_stage', 'write_stage', 'write_count',
                 'process_stage', 'write_close_stage', 'read_close_stage',
                 'helper_stage', 'caller_returned', 'failures', 'first_failures',
                 'raw_failure', 'failure', 'child_read')

    def __init__(self, decrypt_read):
        self.decrypt_read = decrypt_read
        self.lookup, self.key_read = decrypt_read.lookup, decrypt_read.key_read
        self.directory, self.launch = decrypt_read.directory, decrypt_read.launch
        self.job, self.cfg = decrypt_read.job, decrypt_read.cfg
        self.setup_id = decrypt_read.setup_id
        self.used = self.caller_returned = False
        self.stage = self.pair_stage = self.unpack_stage = 'unused'
        self.payload_stage = self.write_stage = self.process_stage = 'unused'
        self.write_close_stage = self.read_close_stage = self.helper_stage = 'unused'
        self.pair = self.read_fd = self.write_fd = self.write_count = None
        self.failures = [None] * 4
        self.first_failures = [None] * 3
        self.raw_failure = self.failure = None
        self.child_read = None

    def remember(self, index, failure):
        self.raw_failure = failure
        if self.failures[index] is None:
            self.failures[index] = failure
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
        self.remember(3, _VaultPipeReadUnavailable())
        raise self.failure from None

    def enter(self, args):
        try:
            if self.used:
                self.refuse()
            self.used = True
            self.stage = 'pending'
            self.helper_stage = 'pending'
            parent, lookup, directory, launch, job = (
                self.decrypt_read, self.lookup, self.directory, self.launch, self.job)
            if (parent.pipe_read is not self or lookup.decrypt_read is not parent
                    or directory.bootstrap_lookup is not lookup
                    or lookup.key_read is not self.key_read
                    or parent.key_read is not self.key_read
                    or parent.lookup is not lookup or parent.directory is not directory
                    or parent.launch is not launch or parent.job is not job
                    or parent.cfg is not self.cfg or lookup.cfg is not self.cfg
                    or directory.launch is not launch or directory.job is not job
                    or directory.cfg is not self.cfg or launch.job is not job
                    or job.get('_worker_launch') is not launch
                    or launch.preparation.directory is not directory
                    or launch.preparation.cfg is not self.cfg
                    or not self.setup_id or job.get('setup_id') != self.setup_id
                    or parent.setup_id != self.setup_id or lookup.setup_id != self.setup_id
                    or parent.cred_key != 'bootstrap_password'
                    or parent.used is not True or parent.request_stage != 'pending'
                    or parent.path_stage != 'returned' or parent.helper_stage != 'pending'
                    or parent.exists_stage != 'returned' or parent.exists_outcome != 'present'
                    or parent.provider_stage != 'pending' or parent.failure is not None
                    or parent.ignored_failure is not None or not self.key_read.known()
                    or lookup.used is not True or lookup.stage != 'pending'
                    or lookup.failure is not None or type(args) is not list
                    or len(args) != 8
                    or args[:7] != ['openssl', 'enc', '-aes-256-cbc', '-d', '-salt', '-pbkdf2', '-in']
                    or args[7] is not parent.candidate_path):
                self.refuse()
        except BaseException as failure:
            self.remember(3, failure)
            raise self.failure from None

    def pair_known(self):
        pair = self.pair
        return (self.pair_stage == self.unpack_stage == 'returned'
                and type(pair) is tuple and len(pair) == 2
                and type(self.read_fd) is int and type(self.write_fd) is int
                and self.read_fd >= 0 and self.write_fd >= 0
                and self.read_fd != self.write_fd
                and self.read_fd is pair[0] and self.write_fd is pair[1])

    def known(self):
        # API return/count metadata alone proves no complete write, FD
        # incarnation/ABA, child ownership or physical resource closure.
        return (self.used is True and self.stage == 'pending'
                and self.failure is None and self.pair_known()
                and self.payload_stage == self.write_stage == 'returned'
                and type(self.write_count) is int and self.write_count >= 0
                and self.process_stage == 'returned'
                and self.write_close_stage == self.read_close_stage == 'returned'
                and self.helper_stage == 'returned' and self.caller_returned is True
                and type(self.child_read) is _VaultChildReadDuty
                and self.child_read.matches(self) and self.child_read.known())
