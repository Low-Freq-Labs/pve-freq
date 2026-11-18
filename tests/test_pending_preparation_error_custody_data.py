"""Actual pure pending preparation with explicit allocation/attribute fault ports.

No gate, server, source, credential, socket or native owner is acquired.
Injected faults affect only pure Python constructor and quarantine assignments.
"""
from contextlib import contextmanager, ExitStack
import builtins
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from freq.services import pilot_component_binding as binding
from freq.services import cluster_pilot_startup as startup


class Control(BaseException):
    pass


class PendingPreparationErrorCustodyData(unittest.TestCase):
    @contextmanager
    def fixture(self, body_error, *, inner_errors=None, outer_errors=None):
        owner = startup.OriginalPilotInstallation()
        events = []
        def constructor(holder):
            events.append(('capacity-init', holder))
            raise body_error
        def assignment(phase, errors):
            def assign(obj, field, value):
                events.append((phase, field))
                if field in errors:
                    raise errors[field]
                builtins.setattr(obj, field, value)
            return assign
        with ExitStack() as stack:
            stack.enter_context(patch.object(binding._GuestCapacity, '__init__', constructor))
            stack.enter_context(patch.object(binding, 'setattr',
                assignment('inner', inner_errors or {}), create=True))
            stack.enter_context(patch.object(startup, 'setattr',
                assignment('outer', outer_errors or {}), create=True))
            yield SimpleNamespace(owner=owner, events=events)

    def assert_all_cleanup_attempted(self, f):
        self.assertEqual([e[1] for e in f.events if e[0] == 'inner'],
                         ['_components_state', '_live', '_admission_uncertain'])
        self.assertEqual([e[1] for e in f.events if e[0] == 'outer'],
                         ['_pending_state', '_pending_retirement_required',
                          '_components_state', '_live', '_admission_uncertain'])
        self.assertIs(f.owner._live, False)
        self.assertIs(f.owner._server, None)
        self.assertIs(f.owner._gate, None)
        self.assertIs(f.owner._native_current_locked(object()), False)

    def test_PP01_successful_pure_preparation_has_no_failure_and_cannot_repeat(self):
        owner = startup.OriginalPilotInstallation()
        owner._prepare_pending_original()
        self.assertEqual(owner._pending_state, 'prepared')
        self.assertEqual(owner._components_state, 'tables-ready')
        self.assertEqual(owner._component_preparation_errors, [None] * 4)
        self.assertEqual(owner._pending_preparation_errors, [None] * 6)
        maps = owner._original_component_tables
        with self.assertRaises(binding._RequestUnavailable):
            owner._prepare_pending_original()
        self.assertIs(owner._original_component_tables, maps)
        self.assertIs(owner._live, False)

    def test_PP02_actual_allocation_error_reaches_outer_unchanged_after_cleanup(self):
        error = MemoryError()
        with self.fixture(error) as f:
            with self.assertRaises(MemoryError) as caught:
                f.owner._prepare_pending_original()
            self.assertIs(caught.exception, error)
            self.assertIs(f.owner._component_preparation_errors[0], error)
            self.assertIs(f.owner._component_preparation_failure, error)
            self.assertIs(f.owner._pending_preparation_errors[0], error)
            self.assertIs(f.owner._pending_preparation_failure, error)
            self.assertIs(f.owner._guest_capacity, f.events[0][1])
            self.assertEqual(f.owner._pending_state, 'retirement-only')
            self.assert_all_cleanup_attempted(f)

    def test_PP03_ordinary_body_remains_private_while_public_refusal_is_generic(self):
        error = OSError('fictional-private-detail')
        with self.fixture(error) as f:
            with self.assertRaises(binding._RequestUnavailable) as caught:
                f.owner._prepare_pending_original()
            self.assertNotIn('fictional-private-detail', str(caught.exception))
            self.assertIs(f.owner._component_preparation_errors[0], error)
            self.assertIs(f.owner._component_preparation_failure, error)
            self.assertIsInstance(f.owner._pending_preparation_errors[0], binding._RequestUnavailable)
            self.assert_all_cleanup_attempted(f)

    def test_PP04_first_memory_keeps_identity_and_later_memory_is_retained(self):
        first, later = MemoryError(), MemoryError()
        with self.fixture(first, inner_errors={'_live': later}) as f:
            with self.assertRaises(MemoryError) as caught:
                f.owner._prepare_pending_original()
            self.assertIs(caught.exception, first)
            self.assertIs(f.owner._component_preparation_errors[2], later)
            self.assertIs(f.owner._component_preparation_failure, first)
            self.assert_all_cleanup_attempted(f)

    def test_PP05_cleanup_memory_outranks_ordinary_without_losing_body(self):
        body, cleanup = OSError('fictional'), MemoryError()
        with self.fixture(body, inner_errors={'_components_state': cleanup}) as f:
            with self.assertRaises(MemoryError) as caught:
                f.owner._prepare_pending_original()
            self.assertIs(caught.exception, cleanup)
            self.assertIs(f.owner._component_preparation_errors[0], body)
            self.assertIs(f.owner._component_preparation_errors[1], cleanup)
            self.assertIs(f.owner._pending_preparation_failure, cleanup)
            self.assert_all_cleanup_attempted(f)

    def test_PP06_first_control_across_inner_and_outer_beats_all_memory(self):
        body, inner, outer = MemoryError(), Control(), Control()
        with self.fixture(body, inner_errors={'_live': inner},
                          outer_errors={'_pending_state': outer}) as f:
            with self.assertRaises(Control) as caught:
                f.owner._prepare_pending_original()
            self.assertIs(caught.exception, inner)
            self.assertIs(f.owner._component_preparation_errors[0], body)
            self.assertIs(f.owner._component_preparation_errors[2], inner)
            self.assertIs(f.owner._pending_preparation_errors[0], inner)
            self.assertIs(f.owner._pending_preparation_errors[1], outer)
            self.assertIs(f.owner._pending_preparation_failure, inner)
            self.assert_all_cleanup_attempted(f)

    def test_PP07_body_control_survives_later_independent_cleanup_faults(self):
        first, inner, outer = Control(), MemoryError(), Control()
        with self.fixture(first, inner_errors={'_components_state': inner},
                          outer_errors={'_live': outer}) as f:
            with self.assertRaises(Control) as caught:
                f.owner._prepare_pending_original()
            self.assertIs(caught.exception, first)
            self.assertIs(f.owner._component_preparation_errors[1], inner)
            self.assertIs(f.owner._pending_preparation_errors[4], outer)
            self.assert_all_cleanup_attempted(f)

    def test_PP08_repeated_init_or_prepare_never_erases_failure_or_retries(self):
        error = MemoryError()
        with self.fixture(error) as f:
            with self.assertRaises(MemoryError):
                f.owner._prepare_pending_original()
            inner = f.owner._component_preparation_errors
            outer = f.owner._pending_preparation_errors
            events = list(f.events)
            f.owner.__init__()
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._prepare_pending_original()
            self.assertEqual(f.events, events)
            self.assertIs(f.owner._component_preparation_errors, inner)
            self.assertIs(f.owner._pending_preparation_errors, outer)
            self.assertIs(f.owner._pending_preparation_failure, error)

    def test_PP09_direct_inner_preparation_preserves_same_memory_and_partial_holder(self):
        error = MemoryError()
        with self.fixture(error) as f:
            with self.assertRaises(MemoryError) as caught:
                f.owner._prepare_original_component_tables()
            self.assertIs(caught.exception, error)
            self.assertIs(f.owner._guest_capacity, f.events[0][1])
            self.assertIs(f.owner._component_preparation_failure, error)
            with self.assertRaises(binding._RequestUnavailable):
                f.owner._prepare_pending_original()
            self.assertEqual(len([e for e in f.events if e[0] == 'capacity-init']), 1)
            self.assertFalse(any(e[0] == 'outer' for e in f.events))

    def test_PP10_priority_is_first_control_then_first_memory_then_first_ordinary(self):
        ordinary, memory, later_memory, control, later_control = (
            ValueError(), MemoryError(), MemoryError(), Control(), Control())
        select = binding._first_preparation_failure
        self.assertIs(select(None, ordinary), ordinary)
        self.assertIs(select(ordinary, memory), memory)
        self.assertIs(select(memory, later_memory), memory)
        self.assertIs(select(memory, control), control)
        self.assertIs(select(control, later_control), control)
        self.assertIs(select(control, memory), control)
