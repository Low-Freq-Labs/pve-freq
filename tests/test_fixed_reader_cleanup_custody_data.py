"""Original reader constructors/close loops; fictional handles and close ports."""
import unittest
from unittest.mock import patch
from freq.services import pilot_fixed_startup_reader as startup
from freq.services import pilot_fixed_server_tls as tls


class Control(BaseException):
    pass


class ReaderCustodyCases:
    def make(self):
        return self.reader(1004, 100.0)

    def owned(self, value):
        for i in range(self.count):
            value._fds[i], value._states[i] = 9000 + i, 'owned'

    def test_RC01_all_known_closes_reverse_and_retains_same_holder_objects(self):
        value = self.make()
        self.owned(value)
        holders = value._fds, value._states, value._ids, value._close_errors
        context = object()
        if self.count == 6:
            value._context, value._context_state = context, 'prepared'
        seen = []
        with patch.object(self.module.os, 'close', seen.append):
            value.close()
            value.close()
        self.assertEqual(seen, [9000 + i for i in reversed(range(self.count))])
        self.assertTrue(all(a is b for a, b in zip(holders, (value._fds, value._states, value._ids, value._close_errors))))
        self.assertEqual(value.close_observations(), ('closed',) * self.count)
        self.assertIsNone(value._close_failure)
        if self.count == 6:
            self.assertIs(value._context, context)
            self.assertEqual(value._context_state, 'retirement-only')

    def test_RC02_all_actual_close_errors_retained_and_first_memory_chosen(self):
        value = self.make()
        self.owned(value)
        errors = [ValueError() for unused in range(self.count)]
        errors[-2], errors[0] = MemoryError(), MemoryError()
        seen = []
        def close(fd):
            seen.append(fd)
            raise errors[fd - 9000]
        with patch.object(self.module.os, 'close', close):
            with self.assertRaises(MemoryError) as caught:
                value.close()
        self.assertIs(caught.exception, errors[-2])
        self.assertIs(value._close_failure, errors[-2])
        self.assertTrue(all(a is b for a, b in zip(value._close_errors, errors)))
        self.assertEqual(seen, [9000 + i for i in reversed(range(self.count))])

    def test_RC03_first_control_outranks_later_control_and_ordinary_errors(self):
        value = self.make()
        self.owned(value)
        first, later = Control(), Control()
        errors = {9000 + self.count - 1: ValueError(), 9000 + self.count - 2: first, 9000: later}
        seen = []
        def close(fd):
            seen.append(fd)
            if fd in errors:
                raise errors[fd]
        with patch.object(self.module.os, 'close', close):
            with self.assertRaises(Control) as caught:
                value.close()
        self.assertIs(caught.exception, first)
        self.assertIs(value._close_failure, first)
        self.assertIs(value._close_errors[0], later)
        self.assertEqual(len(seen), self.count)

    def test_RC04_later_control_outranks_prior_memory_after_all_known_closes(self):
        value = self.make()
        self.owned(value)
        memory, control = MemoryError(), Control()
        errors = {9000 + self.count - 1: memory, 9000: control}
        seen = []
        def close(fd):
            seen.append(fd)
            if fd in errors:
                raise errors[fd]
        with patch.object(self.module.os, 'close', close):
            with self.assertRaises(Control) as caught:
                value.close()
        self.assertIs(caught.exception, control)
        self.assertIs(value._close_failure, control)
        self.assertIs(value._close_errors[-1], memory)
        self.assertEqual(len(seen), self.count)

    def test_RC05_repeated_uncertain_close_never_retries_or_erases_first_failure(self):
        value = self.make()
        value._fds[0], value._states[0] = 9000, 'owned'
        failure = MemoryError()
        seen = []
        def close(fd):
            seen.append(fd)
            raise failure
        with patch.object(self.module.os, 'close', close):
            with self.assertRaises(MemoryError) as caught:
                value.close()
            with self.assertRaises(self.uncertain):
                value.close()
        self.assertIs(caught.exception, failure)
        self.assertIs(value._close_failure, failure)
        self.assertIs(value._close_errors[0], failure)
        self.assertEqual(seen, [9000])

    def test_RC06_pending_unknown_handle_is_never_closed_or_declared_settled(self):
        value = self.make()
        value._states[1] = 'acquire-pending'
        value._fds[0], value._states[0] = 9000, 'owned'
        seen = []
        with patch.object(self.module.os, 'close', seen.append):
            with self.assertRaises(self.uncertain):
                value.close()
        self.assertEqual(seen, [9000])
        self.assertEqual(value._states[1], 'acquire-pending')
        self.assertIsNone(value._close_failure)

    def test_RC07_reinitialization_cannot_replace_retained_holders_end_or_context(self):
        value = self.make()
        self.owned(value)
        holders = value._fds, value._states, value._ids, value._close_errors
        if self.count == 6:
            context = value._context = object()
            value._context_state = 'prepared'
        with self.assertRaises(self.unavailable):
            value.__init__(2004, 200.0)
        self.assertEqual((value._uid, value._end), (1004, 100.0))
        self.assertTrue(all(a is b for a, b in zip(holders, (value._fds, value._states, value._ids, value._close_errors))))
        if self.count == 6:
            self.assertIs(value._context, context)
            self.assertEqual(value._context_state, 'prepared')

    def test_RC08_partial_constructor_is_spent_before_thread_observation_failure(self):
        value = object.__new__(self.reader)
        failure = MemoryError()
        with patch.object(self.module.threading, 'current_thread', side_effect=failure):
            with self.assertRaises(MemoryError) as caught:
                value.__init__(1004, 100.0)
        self.assertIs(caught.exception, failure)
        self.assertIs(value._initialization_spent, True)
        errors = value._close_errors
        with self.assertRaises(self.unavailable):
            value.__init__(2004, 200.0)
        self.assertIs(value._close_errors, errors)
        self.assertEqual(value._end, 100.0)
        self.assertFalse(hasattr(value, '_fds'))

    def test_RC09_foreign_self_refuses_before_attribute_or_thread_effects(self):
        class Foreign:
            def __getattribute__(self, name):
                raise AssertionError('foreign attribute read')
        with patch.object(self.module.threading, 'current_thread', side_effect=AssertionError('thread effect')):
            with self.assertRaises(self.unavailable):
                self.reader.__init__(Foreign(), 1004, 100.0)

    def test_RC10_wrong_thread_refuses_before_close_or_storage_mutation(self):
        value = self.make()
        self.owned(value)
        seen = []
        with patch.object(self.module.threading, 'current_thread', return_value=object()), patch.object(self.module.os, 'close', seen.append):
            with self.assertRaises(self.unavailable):
                value.close()
        self.assertEqual(seen, [])
        self.assertFalse(value._closed)
        self.assertEqual(value._states, ['owned'] * self.count)
        self.assertEqual(value._close_errors, [None] * self.count)


class StartupReaderCleanupCustodyData(ReaderCustodyCases, unittest.TestCase):
    module, reader, count = startup, startup.FixedStartupSourceReader, 8
    unavailable, uncertain = startup.PilotStartupSourcesUnavailable, startup.PilotStartupSourcesClosureUncertain


class TLSReaderCleanupCustodyData(ReaderCustodyCases, unittest.TestCase):
    module, reader, count = tls, tls.FixedServerTLSReader, 6
    unavailable, uncertain = tls.PilotServerTLSUnavailable, tls.PilotServerTLSClosureUncertain
