"""Draft process-local child-context observations; no IO or provider imports."""


class _VaultChildContextUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Required Vault child context cleanup is unavailable.')


class _VaultChildStreamLeaf:
    __slots__ = ('root', 'name', 'used', 'lookup_stage', 'handle', 'truth_stage',
                 'outcome', 'close_stage', 'raw_failure', 'failure', 'first_failures')

    def __init__(self, root, name):
        self.root, self.name = root, name
        self.used = False
        self.lookup_stage = self.truth_stage = self.close_stage = 'unused'
        self.outcome = 'unused'
        self.handle = self.raw_failure = self.failure = None
        self.first_failures = [None] * 3

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
        self.root.remember(failure)

    def known(self):
        if (self.used is not True or self.lookup_stage != 'returned'
                or self.truth_stage != 'returned' or self.failure is not None):
            return False
        if self.outcome == 'absent-field':
            return self.handle is None and self.close_stage == 'unused'
        return (self.outcome == 'present-field' and self.handle is not None
                and self.close_stage == 'returned')


class _VaultChildContextDuty:
    """Prepublished fixed intended cleanup duties, not physical release proof."""
    __slots__ = ('child_read', 'pipe_read', 'decrypt_read', 'lookup', 'key_read',
                 'directory', 'launch', 'job', 'cfg', 'setup_id', 'used', 'stage',
                 'handle', 'leaves', 'selector_stage', 'mode', 'special_stage',
                 'wait_stage', 'body_failure', 'prior_failure', 'wait_failure', 'special_failure',
                 'helper_stage', 'caller_returned', 'raw_failure', 'first_failures',
                 'failure')

    def __init__(self, child_read):
        self.child_read, self.pipe_read = child_read, child_read.pipe_read
        self.decrypt_read, self.lookup = child_read.decrypt_read, child_read.lookup
        self.key_read, self.directory = child_read.key_read, child_read.directory
        self.launch, self.job, self.cfg = child_read.launch, child_read.job, child_read.cfg
        self.setup_id = child_read.setup_id
        self.used = self.caller_returned = False
        self.stage = self.selector_stage = self.special_stage = 'unused'
        self.wait_stage = self.helper_stage = self.mode = 'unused'
        self.handle = self.body_failure = self.prior_failure = None
        self.wait_failure = self.special_failure = None
        self.raw_failure = self.failure = None
        self.first_failures = [None] * 3
        self.leaves = tuple(_VaultChildStreamLeaf(self, name)
                            for name in ('stdout', 'stderr', 'stdin'))

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
        self.remember(_VaultChildContextUnavailable())
        raise self.failure from None

    def matches(self, child):
        return (self.child_read is child and child.context_read is self
                and child.pipe_read is self.pipe_read and child.matches(self.pipe_read)
                and child.decrypt_read is self.decrypt_read and child.lookup is self.lookup
                and child.key_read is self.key_read and child.directory is self.directory
                and child.launch is self.launch and child.job is self.job
                and child.cfg is self.cfg and child.setup_id == self.setup_id)

    def unused(self):
        return (self.used is False and self.stage == self.helper_stage == 'unused'
                and self.failure is None and self.handle is None
                and self.selector_stage == self.special_stage == self.wait_stage == 'unused'
                and self.mode == 'unused' and self.caller_returned is False
                and self.leaves_unused())

    def leaves_unused(self):
        if type(self.leaves) is not tuple or len(self.leaves) != 3:
            return False
        for leaf, name in zip(self.leaves, ('stdout', 'stderr', 'stdin')):
            if (type(leaf) is not _VaultChildStreamLeaf or leaf.root is not self
                    or leaf.name != name or leaf.used is not False
                    or leaf.handle is not None or leaf.failure is not None
                    or leaf.lookup_stage != 'unused' or leaf.truth_stage != 'unused'
                    or leaf.close_stage != 'unused' or leaf.outcome != 'unused'):
                return False
        return True

    def enter(self, child, handle, body):
        # Retained child failure can precede a context body of None if a
        # callback swallowed reentry refusal. Cleanup remains independently
        # due, and that first error cannot be replaced by a later close.
        prior = child.failure
        if self.used is False:
            self.prior_failure, self.body_failure = prior, body
        if prior is not None:
            self.remember(prior)
        if body is not None:
            self.remember(body)
        try:
            if self.used:
                self.refuse()
            self.used = True
            self.stage = self.helper_stage = 'pending'
            self.handle = handle
            if (not self.matches(child) or not self.leaves_unused()
                    or child.used is not True or child.stage != 'pending'
                    or child.helper_stage != 'pending' or child.caller_returned is not False
                    or child.constructor_stage != 'returned' or child.handle is not handle
                    # The entered value may have been rejected by the child
                    # body. Original context exit still owns the returned
                    # constructor handle after known protocol entry.
                    or child.enter_stage != 'returned'
                    or child.exit_stage != 'pending' or child.context.cleanup is not self
                    or body is not None and child.failure is not body
                    or handle is None):
                self.refuse()
        except BaseException as failure:
            self.remember(failure)
            raise self.failure from None

    def known(self):
        if (not self.matches(self.child_read) or self.used is not True
                or self.stage != 'pending' or self.failure is not None
                or self.body_failure is not None or self.mode != 'normal'
                or self.selector_stage != 'returned' or self.special_stage != 'unused'
                or self.wait_stage != 'returned' or self.wait_failure is not None
                or self.helper_stage != 'returned' or self.caller_returned is not True
                or self.handle is not self.child_read.handle
                or type(self.leaves) is not tuple or len(self.leaves) != 3):
            return False
        for leaf, name in zip(self.leaves, ('stdout', 'stderr', 'stdin')):
            if (type(leaf) is not _VaultChildStreamLeaf or leaf.root is not self
                    or leaf.name != name or not leaf.known()):
                return False
        return True
