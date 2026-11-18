"""Private process-local Vault reader observations; no IO or secret values."""


class _VaultKeyReadUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Required Vault key read is unavailable.')


class _VaultKeyReadLeaf:
    __slots__ = ('root', 'path', 'used', 'open_stage', 'handle', 'context',
                 'enter_stage', 'entered_handle', 'read_stage', 'hash_stage',
                 'body_stage', 'exit_stage', 'outcome', 'body_failure',
                 'context_failure', 'first_failures', 'failure')

    def __init__(self, root, path):
        self.root, self.path = root, path
        self.used = False
        self.handle = self.context = self.entered_handle = None
        self.open_stage = self.enter_stage = self.read_stage = 'unused'
        self.hash_stage = self.body_stage = self.exit_stage = 'unused'
        self.outcome = 'unused'
        self.body_failure = self.context_failure = self.failure = None
        self.first_failures = [None] * 3

    def remember(self, failure):
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


class _VaultKeyReadDuty:
    """Preallocated under the original setup lookup; never stores a key."""
    __slots__ = ('lookup', 'directory', 'launch', 'job', 'cfg', 'setup_id',
                 'cred_key', 'used', 'request_stage', 'reader_stage',
                 'caller_returned', 'outcome', 'leaves', 'first_failures',
                 'failure')

    def __init__(self, lookup):
        self.lookup, self.directory = lookup, lookup.directory
        self.launch, self.job, self.cfg = lookup.launch, lookup.job, lookup.cfg
        self.setup_id, self.cred_key = lookup.setup_id, 'bootstrap_password'
        self.used = self.caller_returned = False
        self.request_stage = self.reader_stage = self.outcome = 'unused'
        self.first_failures = [None] * 3
        self.failure = None
        self.leaves = (_VaultKeyReadLeaf(self, '/etc/machine-id'),
                       _VaultKeyReadLeaf(self, '/var/lib/dbus/machine-id'))

    def remember(self, failure):
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
        self.remember(_VaultKeyReadUnavailable())
        raise self.failure from None

    def enter_request(self, cfg, host, cred_key):
        try:
            if self.used:
                self.refuse()
            self.used = True
            self.request_stage = 'pending'
            lookup, directory, launch, job = (
                self.lookup, self.directory, self.launch, self.job)
            if (lookup.key_read is not self or lookup.directory is not directory
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
                    or lookup.cred_key != self.cred_key or cred_key != self.cred_key
                    or lookup.used is not True or lookup.stage != 'pending'
                    or lookup.failure is not None or lookup.requested_host is not host):
                self.refuse()
        except BaseException as failure:
            self.remember(failure)
            raise self.failure from None

    def enter_reader(self):
        if (self.used is not True or self.request_stage != 'pending'
                or self.reader_stage != 'unused' or self.failure is not None):
            self.refuse()
        self.reader_stage = 'pending'
        if type(self.leaves) is not tuple or len(self.leaves) != 2:
            self.refuse()
        for leaf, path in zip(self.leaves, ('/etc/machine-id', '/var/lib/dbus/machine-id')):
            if (type(leaf) is not _VaultKeyReadLeaf or leaf.root is not self
                    or leaf.path != path or leaf.used is not False
                    or leaf.handle is not None or leaf.failure is not None
                    or leaf.open_stage != 'unused'):
                self.refuse()

    def known(self):
        if (self.failure is not None or self.used is not True
                or self.request_stage != 'pending'
                or self.reader_stage != 'returned'
                or self.caller_returned is not True):
            return False
        first, second = self.leaves
        for leaf, path in ((first, '/etc/machine-id'),
                           (second, '/var/lib/dbus/machine-id')):
            if type(leaf) is not _VaultKeyReadLeaf or leaf.root is not self or leaf.path != path:
                return False
        def returned(leaf):
            return (leaf.used is True and leaf.open_stage == 'returned'
                    and leaf.handle is not None and leaf.enter_stage == 'returned'
                    and leaf.entered_handle is leaf.handle
                    and leaf.read_stage == leaf.hash_stage == leaf.body_stage == 'returned'
                    and leaf.exit_stage == 'returned' and leaf.failure is None
                    and leaf.outcome == 'key')
        def missing(leaf):
            return (leaf.used is True and leaf.outcome == 'reported-missing'
                    and issubclass(type(leaf.failure), FileNotFoundError)
                    and ((leaf.handle is None and leaf.open_stage == 'reported-missing'
                          and leaf.enter_stage == leaf.exit_stage == 'unused')
                         or (leaf.handle is not None and leaf.open_stage == 'returned'
                             and leaf.enter_stage == 'returned'
                             and leaf.entered_handle is leaf.handle
                             and leaf.exit_stage == 'returned'
                             and leaf.context_failure is leaf.body_failure
                             and leaf.failure is leaf.body_failure)))
        if self.outcome == 'key':
            return ((returned(first) and second.used is False)
                    or (missing(first) and returned(second)))
        return self.outcome == 'empty' and missing(first) and missing(second)
