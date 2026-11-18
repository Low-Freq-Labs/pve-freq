"""Planning partial-constructor custody; no IO, provider or value imports."""


class _VaultChildConstructorUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Required Vault child constructor is unavailable.')


class _VaultChildConstructorDuty:
    """Original same-child allocation/init API metadata, not native identity."""
    __slots__ = ('child_read', 'pipe_read', 'decrypt_read', 'lookup', 'key_read',
                 'directory', 'launch', 'job', 'cfg', 'setup_id', 'used', 'stage',
                 'class_stage', 'provider', 'initializer', 'allocation_stage',
                 'handle', 'init_stage', 'policy_stage', 'outcome', 'helper_stage',
                 'caller_returned', 'raw_failure', 'first_failures', 'failure')

    def __init__(self, child):
        self.child_read, self.pipe_read = child, child.pipe_read
        self.decrypt_read, self.lookup = child.decrypt_read, child.lookup
        self.key_read, self.directory = child.key_read, child.directory
        self.launch, self.job, self.cfg = child.launch, child.job, child.cfg
        self.setup_id = child.setup_id
        self.used = self.caller_returned = False
        self.stage = self.class_stage = self.allocation_stage = 'unused'
        self.init_stage = self.policy_stage = self.outcome = self.helper_stage = 'unused'
        self.provider = self.initializer = self.handle = self.raw_failure = self.failure = None
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

    def refuse(self):
        first = self.failure
        if first is not None and (not issubclass(type(first), Exception)
                                  or issubclass(type(first), MemoryError)):
            raise first from None
        self.remember(_VaultChildConstructorUnavailable())
        raise self.failure from None

    def matches(self, child):
        return (self.child_read is child and child.constructor_read is self
                and child.pipe_read is self.pipe_read and child.matches(self.pipe_read)
                and child.decrypt_read is self.decrypt_read and child.lookup is self.lookup
                and child.key_read is self.key_read and child.directory is self.directory
                and child.launch is self.launch and child.job is self.job
                and child.cfg is self.cfg and child.setup_id == self.setup_id)

    def unused(self):
        return (self.used is False and self.stage == self.class_stage == 'unused'
                and self.allocation_stage == self.init_stage == self.policy_stage == 'unused'
                and self.helper_stage == self.outcome == 'unused'
                and self.provider is None and self.initializer is None
                and self.handle is None and self.failure is None
                and self.caller_returned is False)

    def enter(self, child, args, stdin, stdout, stderr, pass_fds):
        try:
            if self.used:
                self.refuse()
            self.used = True
            self.stage = self.helper_stage = 'pending'
            pipe, parent = self.pipe_read, self.decrypt_read
            if (not self.matches(child) or child.used is not True
                    or child.stage != 'pending' or child.helper_stage != 'pending'
                    or child.caller_returned is not False or child.failure is not None
                    or child.constructor_stage != 'pending' or child.handle is not None
                    or child.context.root is not child
                    or child.context.cleanup is not child.context_read
                    or not child.context_read.matches(child) or not child.context_read.unused()
                    or pipe.used is not True or pipe.stage != 'pending'
                    or pipe.process_stage != 'pending' or pipe.helper_stage != 'pending'
                    or pipe.failure is not None or not pipe.pair_known()
                    or pipe.payload_stage != 'returned' or pipe.write_stage != 'returned'
                    or type(pipe.write_count) is not int or pipe.write_count < 0
                    or pipe.write_close_stage != 'returned' or pipe.read_close_stage != 'unused'
                    or parent.used is not True or parent.request_stage != 'pending'
                    or parent.helper_stage != 'pending' or parent.provider_stage != 'pending'
                    or parent.exists_stage != 'returned' or parent.exists_outcome != 'present'
                    or parent.failure is not None or parent.ignored_failure is not None
                    or not self.key_read.known()
                    or type(args) is not list or len(args) != 10
                    or args[:7] != ['openssl', 'enc', '-aes-256-cbc', '-d', '-salt', '-pbkdf2', '-in']
                    or args[7] is not parent.candidate_path
                    or args[8:] != ['-pass', f'fd:{pipe.read_fd}']
                    or type(stdin) is not int or stdin != -1
                    or type(stdout) is not int or stdout != -1
                    or type(stderr) is not int or stderr != -1
                    or type(pass_fds) is not list or len(pass_fds) != 1
                    or pass_fds[0] is not pipe.read_fd):
                self.refuse()
        except BaseException as failure:
            self.remember(failure)
            raise self.failure from None

    def known(self):
        # A retained self may contain initialized/partial native fields; these
        # API stages never prove resource birth, release or finalizer timing.
        return (self.matches(self.child_read) and self.used is True
                and self.stage == 'pending' and self.failure is None
                and self.class_stage == self.allocation_stage == self.init_stage == 'returned'
                and self.policy_stage == 'returned' and self.outcome == 'none'
                and type(self.provider) is type and self.initializer is not None
                and type(self.handle) is self.provider
                and self.child_read.handle is self.handle
                and self.helper_stage == 'returned' and self.caller_returned is True)
