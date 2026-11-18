"""Inner auth attempt only, with fictional reader/decrypt/decoder/clock ports.

No fixed file, credential, OpenSSL process or password verification is used.
Outer request broker and native/physical lifetime are outside these witnesses.
"""
from contextlib import contextmanager, ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from freq.services import pilot_auth_input_attempt as auth


class Control(BaseException):
    pass


class AuthInputErrorCustodyData(unittest.TestCase):
    @contextmanager
    def fixture(self, members=(('fixture', 'admin'),)):
        reader = SimpleNamespace(open_fixed=Mock(),
            read_inputs=Mock(return_value=(b'fixture-config', b'fixture-users',
                b'fixture-roles', b'fictional-ciphertext', b'fictional-machine-id')),
            _recheck=Mock(), close=Mock(),
            cleanup_observations=Mock(return_value=('fixture-reader-only',)))
        decrypt = SimpleNamespace(run=Mock(return_value=b'fictional-plaintext'),
            cleanup_observations=Mock(return_value=(
                'unused', 'unused', ('unused', 'unused'),
                ('unused', 'unused', 'unused'), 'unused', 'unused', 'unused')))
        with ExitStack() as stack:
            source_ctor = stack.enter_context(patch.object(auth, 'FixedOriginalAuthReader', return_value=reader))
            decrypt_ctor = stack.enter_context(patch.object(auth, 'OriginalVaultDecrypt', return_value=decrypt))
            stack.enter_context(patch.object(auth.time, 'monotonic', return_value=1.0))
            decoder = stack.enter_context(patch.object(auth, 'decode_retained_original_inputs',
                return_value=((), members, 'fixture-service', None)))
            exact_hash = stack.enter_context(patch.object(auth, 'exact_original_auth_hash',
                return_value='fictional-hash-data'))
            attempt = auth.OriginalAuthInputAttempt(1003, 1004, 30.0)
            yield SimpleNamespace(attempt=attempt, reader=reader, decrypt=decrypt,
                source_ctor=source_ctor, decrypt_ctor=decrypt_ctor,
                decoder=decoder, exact_hash=exact_hash)

    def assert_retired(self, f):
        f.reader.close.assert_called_once_with()
        self.assertEqual(f.attempt._state, 'retired')
        self.assertIsNone(f.attempt._user)
        self.assertIsNone(f.attempt._role)
        self.assertIsNone(f.attempt._hash)
        self.assertIs(f.attempt._verified, False)
        self.assertEqual(f.attempt._end, 30.0)
        self.assertIs(f.attempt._reader, f.reader)
        self.assertIs(f.attempt._decrypt, f.decrypt)

    def test_AI01_success_keeps_same_holders_and_empty_error_storage(self):
        with self.fixture() as f:
            errors = f.attempt._input_errors
            self.assertIs(f.attempt.acquire('fixture'), f.attempt)
            self.assertEqual(f.attempt.original_user, 'fixture')
            self.assertEqual(f.attempt.role, 'admin')
            f.attempt.retire()
            self.assertIs(f.attempt._input_errors, errors)
            self.assertEqual(errors, [None] * 4)
            self.assertIsNone(f.attempt._input_failure)
            self.assertEqual(f.attempt._cleanup, 'locally-settled')
            self.assert_retired(f)

    def test_AI02_body_memory_is_same_after_both_cleanup_observations(self):
        error = MemoryError()
        with self.fixture() as f:
            f.reader.read_inputs.side_effect = error
            with self.assertRaises(MemoryError) as caught:
                f.attempt.acquire('fixture')
            self.assertIs(caught.exception, error)
            self.assertIs(f.attempt._input_errors[0], error)
            self.assertIs(f.attempt._input_failure, error)
            f.decrypt.cleanup_observations.assert_called_once_with()
            f.decrypt.run.assert_not_called()
            self.assert_retired(f)

    def test_AI03_cleanup_memory_outranks_ordinary_body_without_loss(self):
        body, cleanup = ValueError('fictional private body'), MemoryError()
        with self.fixture() as f:
            f.reader.read_inputs.side_effect = body
            f.reader.close.side_effect = cleanup
            with self.assertRaises(MemoryError) as caught:
                f.attempt.acquire('fixture')
            self.assertIs(caught.exception, cleanup)
            self.assertIs(f.attempt._input_errors[0], body)
            self.assertIs(f.attempt._input_errors[1], cleanup)
            self.assertIs(f.attempt._input_errors[3], cleanup)
            self.assertIs(f.attempt._input_failure, cleanup)
            f.decrypt.cleanup_observations.assert_called_once_with()
            self.assert_retired(f)

    def test_AI04_first_cleanup_control_outranks_body_memory_and_later_control(self):
        body, source, decrypt = MemoryError(), Control(), Control()
        with self.fixture() as f:
            f.reader.read_inputs.side_effect = body
            f.reader.close.side_effect = source
            f.decrypt.cleanup_observations.side_effect = decrypt
            with self.assertRaises(Control) as caught:
                f.attempt.acquire('fixture')
            self.assertIs(caught.exception, source)
            self.assertIs(f.attempt._input_errors[0], body)
            self.assertIs(f.attempt._input_errors[1], source)
            self.assertIs(f.attempt._input_errors[2], decrypt)
            self.assertIs(f.attempt._input_failure, source)
            self.assert_retired(f)

    def test_AI05_body_control_remains_first_across_cleanup_memory_and_control(self):
        body, source, decrypt = Control(), MemoryError(), Control()
        with self.fixture() as f:
            f.reader.read_inputs.side_effect = body
            f.reader.close.side_effect = source
            f.decrypt.cleanup_observations.side_effect = decrypt
            with self.assertRaises(Control) as caught:
                f.attempt.acquire('fixture')
            self.assertIs(caught.exception, body)
            self.assertIs(f.attempt._input_errors[1], source)
            self.assertIs(f.attempt._input_errors[2], decrypt)
            self.assertIs(f.attempt._input_failure, body)
            self.assert_retired(f)

    def test_AI06_later_decrypt_observation_memory_beats_ordinary_close(self):
        body, source, decrypt = OSError(), ValueError(), MemoryError()
        with self.fixture() as f:
            f.reader.read_inputs.side_effect = body
            f.reader.close.side_effect = source
            f.decrypt.cleanup_observations.side_effect = decrypt
            with self.assertRaises(MemoryError) as caught:
                f.attempt.acquire('fixture')
            self.assertIs(caught.exception, decrypt)
            self.assertIs(f.attempt._input_errors[0], body)
            self.assertIs(f.attempt._input_errors[1], source)
            self.assertIs(f.attempt._input_errors[2], decrypt)
            self.assertIs(f.attempt._input_failure, decrypt)
            self.assert_retired(f)

    def test_AI07_absent_member_cannot_return_none_after_cleanup_memory(self):
        cleanup = MemoryError()
        with self.fixture(members=()) as f:
            f.reader.close.side_effect = cleanup
            with self.assertRaises(MemoryError) as caught:
                f.attempt.acquire('fixture')
            self.assertIs(caught.exception, cleanup)
            self.assertIsNone(f.attempt._input_errors[0])
            self.assertIs(f.attempt._input_errors[1], cleanup)
            self.assertIs(f.attempt._input_failure, cleanup)
            f.decrypt.run.assert_not_called()
            f.exact_hash.assert_not_called()
            self.assert_retired(f)

    def test_AI08_ordinary_body_refusal_is_generic_with_private_actual_failure(self):
        body = ValueError('fictional private payload')
        with self.fixture() as f:
            f.reader.read_inputs.side_effect = body
            with self.assertRaises(auth.PilotAuthInputUnavailable) as caught:
                f.attempt.acquire('fixture')
            self.assertNotIn('fictional private payload', str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)
            self.assertIs(f.attempt._input_errors[0], body)
            self.assertIs(f.attempt._input_failure, body)
            self.assert_retired(f)

    def test_AI09_uncertain_retirement_and_reinit_cannot_retry_or_erase(self):
        body, close = MemoryError(), OSError()
        with self.fixture() as f:
            f.reader.read_inputs.side_effect = body
            f.reader.close.side_effect = close
            with self.assertRaises(MemoryError):
                f.attempt.acquire('fixture')
            errors = f.attempt._input_errors
            before = list(errors)
            with self.assertRaises(auth.PilotAuthInputClosureUncertain):
                f.attempt.retire()
            with self.assertRaises(auth.PilotAuthInputUnavailable):
                auth.OriginalAuthInputAttempt.__init__(f.attempt, 1005, 1006, 9999.0)
            with self.assertRaises(auth.PilotAuthInputUnavailable):
                f.attempt.acquire('fixture')
            self.assertIs(f.attempt._input_errors, errors)
            self.assertEqual(errors, before)
            self.assertIs(f.attempt._input_failure, body)
            f.source_ctor.assert_called_once_with(1003, 1004, 30.0)
            f.decrypt_ctor.assert_called_once_with()
            self.assert_retired(f)

    def test_AI10_retained_reinit_keeps_same_holders_hash_and_original_end(self):
        with self.fixture() as f:
            f.attempt.acquire('fixture')
            errors = f.attempt._input_errors
            stored = f.attempt._hash
            with self.assertRaises(auth.PilotAuthInputUnavailable):
                auth.OriginalAuthInputAttempt.__init__(f.attempt, 1005, 1006, 9999.0)
            self.assertIs(f.attempt._input_errors, errors)
            self.assertIs(f.attempt._reader, f.reader)
            self.assertIs(f.attempt._decrypt, f.decrypt)
            self.assertIs(f.attempt._hash, stored)
            self.assertEqual(f.attempt._end, 30.0)
            self.assertEqual(f.attempt._state, 'retained')
            f.source_ctor.assert_called_once_with(1003, 1004, 30.0)
            f.decrypt_ctor.assert_called_once_with()
            f.attempt.retire()
            self.assert_retired(f)

    def test_AI11_partial_holder_constructor_failure_spends_initializer(self):
        obj = object.__new__(auth.OriginalAuthInputAttempt)
        error = MemoryError()
        with patch.object(auth, 'FixedOriginalAuthReader', side_effect=error) as source, patch.object(
                auth, 'OriginalVaultDecrypt') as decrypt:
            with self.assertRaises(MemoryError) as caught:
                auth.OriginalAuthInputAttempt.__init__(obj, 1003, 1004, 30.0)
            self.assertIs(caught.exception, error)
            self.assertEqual(obj._state, 'constructing')
            errors = obj._input_errors
            with self.assertRaises(auth.PilotAuthInputUnavailable):
                auth.OriginalAuthInputAttempt.__init__(obj, 1003, 1004, 9999.0)
            self.assertIs(obj._input_errors, errors)
            source.assert_called_once_with(1003, 1004, 30.0)
            decrypt.assert_not_called()

    def test_AI12_foreign_self_refuses_before_attributes_or_holder_factories(self):
        class Foreign:
            def __getattribute__(self, name):
                raise AssertionError('foreign attribute hook')
            def __setattr__(self, name, value):
                raise AssertionError('foreign assignment hook')
        with patch.object(auth, 'FixedOriginalAuthReader') as source, patch.object(
                auth, 'OriginalVaultDecrypt') as decrypt:
            with self.assertRaises(auth.PilotAuthInputUnavailable):
                auth.OriginalAuthInputAttempt.__init__(Foreign(), 1003, 1004, 30.0)
            source.assert_not_called()
            decrypt.assert_not_called()
