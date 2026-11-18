"""Private child API observations; no IO, provider or secret value slots."""

from freq.core.vault_child_context import _VaultChildContextDuty
from freq.core.vault_child_constructor import _VaultChildConstructorDuty


class _VaultChildReadUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Required Vault child acquisition is unavailable.')


class _VaultChildReadDuty:
    """One prepublished original child attempt, never native identity proof."""
    __slots__ = ('pipe_read', 'decrypt_read', 'lookup', 'key_read', 'directory',
                 'launch', 'job', 'cfg', 'setup_id', 'used', 'stage',
                 'constructor_stage', 'handle', 'context', 'enter_stage',
                 'entered_handle', 'body_stage', 'communicate_stage',
                 'unpack_stage', 'kill_stage', 'timeout_wait_stage', 'poll_stage',
                 'exit_stage', 'result_stage', 'helper_stage', 'caller_returned',
                 'context_failure', 'failures', 'first_failures', 'raw_failure',
                 'failure', 'context_read', 'constructor_read')

    def __init__(self, pipe_read):
        self.pipe_read = pipe_read
        self.decrypt_read, self.lookup = pipe_read.decrypt_read, pipe_read.lookup
        self.key_read, self.directory = pipe_read.key_read, pipe_read.directory
        self.launch, self.job, self.cfg = pipe_read.launch, pipe_read.job, pipe_read.cfg
        self.setup_id = pipe_read.setup_id
        self.used = self.caller_returned = False
        self.stage = self.constructor_stage = self.enter_stage = 'unused'
        self.body_stage = self.communicate_stage = self.unpack_stage = 'unused'
        self.kill_stage = self.timeout_wait_stage = self.poll_stage = 'unused'
        self.exit_stage = self.result_stage = self.helper_stage = 'unused'
        self.handle = self.context = self.entered_handle = None
        self.context_failure = self.raw_failure = self.failure = None
        self.context_read = None
        self.constructor_read = None
        self.failures = [None] * 4
        self.first_failures = [None] * 3

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
        self.remember(3, _VaultChildReadUnavailable())
        raise self.failure from None

    def matches(self, pipe):
        parent, lookup, directory, launch, job = (
            self.decrypt_read, self.lookup, self.directory, self.launch, self.job)
        return (self.pipe_read is pipe and pipe.child_read is self
                and pipe.decrypt_read is parent and parent.pipe_read is pipe
                and pipe.lookup is lookup and parent.lookup is lookup
                and lookup.decrypt_read is parent
                and pipe.key_read is self.key_read and parent.key_read is self.key_read
                and lookup.key_read is self.key_read
                and pipe.directory is directory and parent.directory is directory
                and lookup.directory is directory and directory.bootstrap_lookup is lookup
                and pipe.launch is launch and parent.launch is launch
                and lookup.launch is launch and directory.launch is launch
                and pipe.job is job and parent.job is job and lookup.job is job
                and directory.job is job and launch.job is job
                and job.get('_worker_launch') is launch
                and launch.preparation.directory is directory
                and pipe.cfg is self.cfg and parent.cfg is self.cfg
                and lookup.cfg is self.cfg and directory.cfg is self.cfg
                and launch.preparation.cfg is self.cfg
                and bool(self.setup_id) and job.get('setup_id') == self.setup_id
                and pipe.setup_id == parent.setup_id == lookup.setup_id == self.setup_id)

    def enter(self, args, input, capture_output, timeout, pass_fds):
        try:
            if self.used:
                self.refuse()
            self.used = True
            self.stage = self.helper_stage = 'pending'
            constructor = self.constructor_read
            if (type(constructor) is not _VaultChildConstructorDuty
                    or not constructor.matches(self) or not constructor.unused()):
                self.refuse()
            context = self.context_read
            if (type(context) is not _VaultChildContextDuty
                    or not context.matches(self) or not context.unused()):
                self.refuse()
            pipe, parent, lookup = self.pipe_read, self.decrypt_read, self.lookup
            if (not self.matches(pipe)
                    or pipe.used is not True or pipe.stage != 'pending'
                    or pipe.helper_stage != 'pending' or pipe.process_stage != 'pending'
                    or pipe.failure is not None or pipe.caller_returned is not False
                    or not pipe.pair_known()
                    or pipe.payload_stage != 'returned' or pipe.write_stage != 'returned'
                    or type(pipe.write_count) is not int or pipe.write_count < 0
                    or pipe.write_close_stage != 'returned' or pipe.read_close_stage != 'unused'
                    or parent.used is not True or parent.request_stage != 'pending'
                    or parent.helper_stage != 'pending' or parent.provider_stage != 'pending'
                    or parent.exists_stage != 'returned' or parent.exists_outcome != 'present'
                    or parent.failure is not None or parent.ignored_failure is not None
                    or parent.cred_key != 'bootstrap_password'
                    or lookup.used is not True or lookup.stage != 'pending'
                    or lookup.failure is not None or not self.key_read.known()
                    or type(args) is not list or len(args) != 10
                    or args[:7] != ['openssl', 'enc', '-aes-256-cbc', '-d', '-salt', '-pbkdf2', '-in']
                    or args[7] is not parent.candidate_path
                    or args[8:] != ['-pass', f'fd:{pipe.read_fd}']
                    or type(input) is not bytes or input != b''
                    or capture_output is not True or type(timeout) is not int or timeout != 10
                    or type(pass_fds) is not list or len(pass_fds) != 1
                    or pass_fds[0] is not pipe.read_fd):
                self.refuse()
        except BaseException as failure:
            self.remember(3, failure)
            raise self.failure from None

    def known(self):
        # Context API return does not expose its internal stream closes or reap.
        return (self.matches(self.pipe_read) and self.used is True
                and self.stage == 'pending' and self.failure is None
                and self.constructor_stage == self.enter_stage == 'returned'
                and self.handle is not None and self.entered_handle is self.handle
                and self.body_stage == self.communicate_stage == self.unpack_stage == 'returned'
                and self.kill_stage == self.timeout_wait_stage == 'unused'
                and self.poll_stage == self.exit_stage == self.result_stage == 'returned'
                and self.context_failure is None
                and self.helper_stage == 'returned' and self.caller_returned is True
                and type(self.context_read) is _VaultChildContextDuty
                and self.context_read.matches(self) and self.context_read.known()
                and type(self.constructor_read) is _VaultChildConstructorDuty
                and self.constructor_read.matches(self) and self.constructor_read.known())
