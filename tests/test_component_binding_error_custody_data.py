"""Actual binding with fictional constructors and quarantine assignment faults.

These witnesses acquire no native gate, source, credential, socket or server.
They prove local caught-error retention, not original physical retirement.
"""
from contextlib import contextmanager
import builtins
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from freq.services import pilot_component_binding as binding
from test_fleet_component_retention_data import FleetComponentRetentionData


class Control(BaseException):
    pass


class ComponentBindingErrorCustodyData(unittest.TestCase):
    @contextmanager
    def fixture(self, body_error, cleanup_errors=None):
        with FleetComponentRetentionData().fixture() as f:
            events = []
            broker = f.owner._server._pilot_requests
            errors = cleanup_errors or {}

            def assign(target, field, value):
                key = ('owner' if target is f.owner else 'broker', field)
                events.append(key)
                if key in errors:
                    raise errors[key]
                builtins.setattr(target, field, value)

            f.ports['OriginalPilotAuthAttempts'].side_effect = body_error
            with patch.object(binding, 'setattr', assign, create=True):
                yield SimpleNamespace(owner=f.owner, broker=broker,
                    events=events, ports=f.ports, read=f.read)

    def assert_cleanup(self, f):
        self.assertEqual(f.events, [
            ('owner', '_components_state'), ('owner', '_live'),
            ('owner', '_admission_uncertain'), ('broker', '_live')])
        self.assertIs(f.owner._live, False)
        self.assertIs(f.broker._live, False)
        self.assertIs(f.owner._native_current_locked(object()), False)
        f.ports['OriginalAuthCommit'].assert_not_called()
        f.ports['OriginalPilotDispatch'].assert_not_called()

    def test_BC01_constructor_memory_identity_after_all_quarantine_steps(self):
        error = MemoryError('fictional allocation')
        with self.fixture(error) as f:
            with self.assertRaises(MemoryError) as caught:
                f.owner._bind_original_components()
            self.assertIs(caught.exception, error)
            self.assertIs(f.owner._component_binding_errors[0], error)
            self.assertIs(f.owner._component_binding_failure, error)
            self.assertEqual(f.owner._components_state, 'retirement-only')
            self.assert_cleanup(f)

    def test_BC02_cleanup_memory_outranks_ordinary_and_keeps_both(self):
        body, cleanup = OSError('fictional private'), MemoryError()
        with self.fixture(body, {('owner', '_components_state'): cleanup}) as f:
            with self.assertRaises(MemoryError) as caught:
                f.owner._bind_original_components()
            self.assertIs(caught.exception, cleanup)
            self.assertIs(f.owner._component_binding_errors[0], body)
            self.assertIs(f.owner._component_binding_errors[1], cleanup)
            self.assertIs(f.owner._component_binding_failure, cleanup)
            self.assert_cleanup(f)

    def test_BC03_first_control_outranks_body_memory_and_later_control(self):
        body, first, later = MemoryError(), Control(), Control()
        with self.fixture(body, {('owner', '_live'): first,
                                ('broker', '_live'): later}) as f:
            with self.assertRaises(Control) as caught:
                f.owner._bind_original_components()
            self.assertIs(caught.exception, first)
            self.assertIs(f.owner._component_binding_errors[0], body)
            self.assertIs(f.owner._component_binding_errors[2], first)
            self.assertIs(f.owner._component_binding_errors[4], later)
            self.assertIs(f.owner._component_binding_failure, first)
            self.assert_cleanup(f)

    def test_BC04_body_control_survives_all_later_cleanup_failures(self):
        body, memory, later = Control(), MemoryError(), Control()
        with self.fixture(body, {('owner', '_components_state'): memory,
                                ('owner', '_admission_uncertain'): later}) as f:
            with self.assertRaises(Control) as caught:
                f.owner._bind_original_components()
            self.assertIs(caught.exception, body)
            self.assertIs(f.owner._component_binding_errors[1], memory)
            self.assertIs(f.owner._component_binding_errors[3], later)
            self.assertIs(f.owner._component_binding_failure, body)
            self.assert_cleanup(f)

    def test_BC05_first_memory_is_stable_and_later_memories_are_retained(self):
        body, first, later = ValueError(), MemoryError(), MemoryError()
        with self.fixture(body, {('owner', '_live'): first,
                                ('broker', '_live'): later}) as f:
            with self.assertRaises(MemoryError) as caught:
                f.owner._bind_original_components()
            self.assertIs(caught.exception, first)
            self.assertIs(f.owner._component_binding_errors[2], first)
            self.assertIs(f.owner._component_binding_errors[4], later)
            self.assertIs(f.owner._component_binding_failure, first)
            self.assert_cleanup(f)

    def test_BC06_repeat_init_and_binding_cannot_erase_or_retry(self):
        error = MemoryError()
        with self.fixture(error) as f:
            with self.assertRaises(MemoryError):
                f.owner._bind_original_components()
            errors = f.owner._component_binding_errors
            before = list(errors)
            events = list(f.events)
            references = f.owner._references
            f.owner.__init__()
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._bind_original_components()
            self.assertIs(f.owner._component_binding_errors, errors)
            self.assertEqual(errors, before)
            self.assertIs(f.owner._component_binding_failure, error)
            self.assertIs(f.owner._references, references)
            self.assertEqual(f.events, events)
            f.ports['OriginalPilotAuthAttempts'].assert_called_once_with(f.owner)
            f.read.assert_called_once_with()
            self.assert_cleanup(f)

    def test_BC07_partial_reader_memory_keeps_same_object_and_no_dispatch(self):
        error = MemoryError()
        retained = []

        def initialize(component, owner):
            self.assertIs(owner._fleet_targets_reader, component)
            retained.append(component)
            raise error

        with FleetComponentRetentionData().fixture() as f, patch.object(
                binding.OriginalPilotFleetTargets, '__init__', initialize):
            with self.assertRaises(MemoryError) as caught:
                f.owner._bind_original_components()
            self.assertIs(caught.exception, error)
            self.assertIs(f.owner._fleet_targets_reader, retained[0])
            self.assertIs(f.owner._component_binding_errors[0], error)
            self.assertIs(f.owner._component_binding_failure, error)
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._bind_original_components()
            self.assertEqual(len(retained), 1)
            f.ports['OriginalPilotDispatch'].assert_not_called()
            self.assertIs(f.owner._live, False)
            self.assertIs(f.owner._server._pilot_requests._live, False)
            self.assertIs(f.owner._native_current_locked(object()), False)

    def test_BC08_ordinary_refusal_is_generic_but_private_errors_are_retained(self):
        body, cleanup = OSError('fictional private body'), ValueError('fictional private cleanup')
        with self.fixture(body, {('owner', '_live'): cleanup}) as f:
            with self.assertRaises(binding._RequestUnavailable) as caught:
                f.owner._bind_original_components()
            self.assertEqual(str(caught.exception), '')
            self.assertTrue(caught.exception.__suppress_context__)
            self.assertIs(f.owner._component_binding_errors[0], body)
            self.assertIs(f.owner._component_binding_errors[2], cleanup)
            self.assertIs(f.owner._component_binding_failure, body)
            self.assert_cleanup(f)
