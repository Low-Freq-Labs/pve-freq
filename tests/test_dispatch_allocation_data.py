"""UNRUN fictional dispatch/read/cleanup/refusal ports; no real HTTP/native."""
import unittest
from types import SimpleNamespace
from freq.services import pilot_cluster_dispatch as source


class DispatchAllocationData(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.body_error = self.cleanup_error = self.refusal_error = None
        self.original = SimpleNamespace(operation='read')
        self.dispatch = source.OriginalPilotDispatch.__new__(source.OriginalPilotDispatch)
        # Explicit fictional ports; bypass no real original owner in production.
        self.dispatch._owned = lambda handler: self.original
        self.dispatch._reads = SimpleNamespace(admit_read=self.admit,
            write_admitted_response=self.write, retire_handler_read=self.retire)
        self.dispatch._write_refusal = self.refuse
        self.handler = object()

    def admit(self, handler):
        self.events.append('body')
        if self.body_error is not None: raise self.body_error
        return object()

    def write(self, handler, response):
        self.events.append('write')

    def retire(self, handler):
        self.events.append('cleanup')
        if self.cleanup_error is not None: raise self.cleanup_error

    def refuse(self, handler, error):
        self.events.append(('refusal', error))
        if self.refusal_error is not None: raise self.refusal_error

    def test_DA01_body_allocation_propagates_after_existing_cleanup_without_refusal(self):
        error = self.body_error = MemoryError()
        with self.assertRaises(MemoryError) as caught: self.dispatch.run(self.handler)
        self.assertIs(caught.exception, error)
        self.assertEqual(self.events, ['body', 'cleanup'])

    def test_DA02_cleanup_allocation_supersedes_ordinary_body_before_refusal(self):
        self.body_error = source._RequestUnavailable()
        error = self.cleanup_error = MemoryError()
        with self.assertRaises(MemoryError) as caught: self.dispatch.run(self.handler)
        self.assertIs(caught.exception, error)
        self.assertEqual(self.events, ['body', 'cleanup'])

    def test_DA03_body_allocation_survives_ordinary_cleanup_error(self):
        error = self.body_error = MemoryError()
        self.cleanup_error = source._RequestUnavailable()
        with self.assertRaises(MemoryError) as caught: self.dispatch.run(self.handler)
        self.assertIs(caught.exception, error)
        self.assertEqual(self.events, ['body', 'cleanup'])

    def test_DA04_first_allocation_between_body_and_cleanup_remains_primary(self):
        error = self.body_error = MemoryError('first')
        self.cleanup_error = MemoryError('later')
        with self.assertRaises(MemoryError) as caught: self.dispatch.run(self.handler)
        self.assertIs(caught.exception, error)
        self.assertEqual(self.events, ['body', 'cleanup'])

    def test_DA05_cleanup_control_overrides_body_allocation(self):
        self.body_error = MemoryError()
        error = self.cleanup_error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt) as caught: self.dispatch.run(self.handler)
        self.assertIs(caught.exception, error)
        self.assertEqual(self.events, ['body', 'cleanup'])

    def test_DA06_body_control_survives_cleanup_allocation(self):
        error = self.body_error = KeyboardInterrupt()
        self.cleanup_error = MemoryError()
        with self.assertRaises(KeyboardInterrupt) as caught: self.dispatch.run(self.handler)
        self.assertIs(caught.exception, error)
        self.assertEqual(self.events, ['body', 'cleanup'])

    def test_DA07_refusal_allocation_propagates_without_another_response_attempt(self):
        ordinary = self.body_error = source._RequestUnavailable()
        error = self.refusal_error = MemoryError()
        with self.assertRaises(MemoryError) as caught: self.dispatch.run(self.handler)
        self.assertIs(caught.exception, error)
        self.assertEqual(self.events, ['body', 'cleanup', ('refusal', ordinary)])

    def test_DA08_ordinary_refusal_path_remains_after_cleanup(self):
        error = self.body_error = source._RequestUnavailable()
        self.dispatch.run(self.handler)
        self.assertEqual(self.events, ['body', 'cleanup', ('refusal', error)])

    def test_DA09_success_retains_original_write_then_cleanup_order(self):
        self.dispatch.run(self.handler)
        self.assertEqual(self.events, ['body', 'write', 'cleanup'])

    def test_DA10_first_genuine_control_between_two_controls_is_not_replaced(self):
        error = self.body_error = KeyboardInterrupt()
        self.cleanup_error = SystemExit()
        with self.assertRaises(KeyboardInterrupt) as caught: self.dispatch.run(self.handler)
        self.assertIs(caught.exception, error)
        self.assertEqual(self.events, ['body', 'cleanup'])
