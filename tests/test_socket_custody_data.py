"""UNRUN fictional socket-factory/close DATA; zero native fixture authority.

Every constructor is patched before a proposed call. Stand-ins and seeded
pending states are not actual native fault injection, fd or physical proof.
"""
import unittest
from unittest.mock import patch

from freq.services import node_read_tls as source


class FictionalSocket:
    def __init__(self, error=None):
        self.close_calls, self.error = 0, error

    def close(self):
        self.close_calls += 1
        if self.error is not None: raise self.error


class SocketCustodyData(unittest.TestCase):
    def test_SD01_known_unstarted_close_is_once_resourcefree_DATA(self):
        duty = source.OriginalSocket()
        with patch.object(source.socket, 'socket') as factory:
            duty.close()
            duty.close()
            factory.assert_not_called()
        self.assertTrue(duty._spent)
        self.assertIsNone(duty._socket)
        self.assertEqual(duty._acquisition, 'unstarted')
        self.assertEqual(duty._closure, 'returned-no-acquisition')

    def test_SD02_pending_precedes_factory_and_known_return_is_retained(self):
        duty = source.OriginalSocket()
        fake = FictionalSocket()
        seen = []
        def fictional_factory(*args):
            seen.append((duty._acquisition, duty._closure, args))
            return fake
        with patch.object(source.socket, 'socket', side_effect=fictional_factory): duty.acquire(4)
        self.assertEqual(seen, [('acquire-pending', 'unattempted',
            (source.socket.AF_INET, source.socket.SOCK_STREAM))])
        self.assertIs(duty._socket, fake)
        self.assertEqual(duty._acquisition, 'owned')

    def test_SD03_second_acquire_never_replaces_the_known_handle(self):
        duty = source.OriginalSocket()
        fake = FictionalSocket()
        with patch.object(source.socket, 'socket', return_value=fake) as factory:
            duty.acquire(6)
            with self.assertRaises(ValueError): duty.acquire(4)
            factory.assert_called_once_with(source.socket.AF_INET6, source.socket.SOCK_STREAM)
        self.assertIs(duty._socket, fake)

    def test_SD04_constructor_error_remains_pending_not_retried_or_closed_as_absent(self):
        duty = source.OriginalSocket()
        with patch.object(source.socket, 'socket', side_effect=OSError('fictional')) as factory:
            with self.assertRaises(OSError): duty.acquire(4)
            with self.assertRaises(ValueError): duty.acquire(4)
            factory.assert_called_once()
        self.assertEqual(duty._acquisition, 'acquire-pending')
        with self.assertRaises(ValueError): duty.close()
        self.assertEqual(duty._closure, 'uncertain-acquisition')
        with self.assertRaises(ValueError): duty.close()

    def test_SD05_constructor_control_is_preserved_with_unknown_handle_duty(self):
        duty = source.OriginalSocket()
        control = KeyboardInterrupt('fictional constructor control')
        with patch.object(source.socket, 'socket', side_effect=control):
            with self.assertRaises(KeyboardInterrupt) as caught: duty.acquire(4)
        self.assertIs(caught.exception, control)
        self.assertIsNone(duty._socket)
        self.assertEqual(duty._acquisition, 'acquire-pending')
        with self.assertRaises(ValueError): duty.close()
        self.assertTrue(duty._spent)

    def test_SD06_known_close_return_retains_same_handle_and_never_closes_twice(self):
        duty = source.OriginalSocket()
        fake = FictionalSocket()
        with patch.object(source.socket, 'socket', return_value=fake): duty.acquire(4)
        duty.close()
        self.assertIs(duty._socket, fake)
        self.assertEqual(duty._closure, 'returned')
        self.assertTrue(duty._spent)
        duty.close()
        self.assertEqual(fake.close_calls, 1)

    def test_SD07_close_error_retains_handle_and_pending_without_second_close(self):
        duty = source.OriginalSocket()
        fake = FictionalSocket(OSError('fictional close error'))
        with patch.object(source.socket, 'socket', return_value=fake): duty.acquire(4)
        with self.assertRaises(OSError): duty.close()
        self.assertIs(duty._socket, fake)
        self.assertEqual(duty._closure, 'close-pending')
        self.assertTrue(duty._spent)
        with self.assertRaises(ValueError): duty.close()
        self.assertEqual(fake.close_calls, 1)

    def test_SD08_close_control_is_preserved_and_original_stays_retained(self):
        duty = source.OriginalSocket()
        control = SystemExit('fictional close control')
        fake = FictionalSocket(control)
        with patch.object(source.socket, 'socket', return_value=fake): duty.acquire(4)
        with self.assertRaises(SystemExit) as caught: duty.close()
        self.assertIs(caught.exception, control)
        self.assertIs(duty._socket, fake)
        self.assertEqual(duty._closure, 'close-pending')
        with self.assertRaises(ValueError): duty.close()
        self.assertEqual(fake.close_calls, 1)

    def test_SD09_seeded_pending_known_slot_can_close_without_erasing_acquire_uncertainty(self):
        duty = source.OriginalSocket()
        fake = FictionalSocket()
        duty._socket, duty._acquisition = fake, 'acquire-pending'
        duty.close()
        self.assertIs(duty._socket, fake)
        self.assertEqual(duty._acquisition, 'acquire-pending')
        self.assertEqual(duty._closure, 'returned')
        self.assertEqual(fake.close_calls, 1)
        # Seeded state, not observed native lost-return coverage or job proof.

    def test_SD10_invalid_version_has_no_constructor_effect_before_known_close(self):
        for version in (True, 0, 7, '4'):
            duty = source.OriginalSocket()
            with patch.object(source.socket, 'socket') as factory:
                with self.assertRaises(ValueError): duty.acquire(version)
                factory.assert_not_called()
            self.assertEqual(duty._acquisition, 'unstarted')
            duty.close()
            self.assertEqual(duty._closure, 'returned-no-acquisition')

    def test_SD11_known_inconsistent_slot_state_refuses_without_arbitrary_close(self):
        duty = source.OriginalSocket()
        fake = FictionalSocket()
        duty._socket = fake  # Fictional malformed state, never an owner grant.
        with self.assertRaises(ValueError): duty.close()
        self.assertEqual(fake.close_calls, 0)
        self.assertIs(duty._socket, fake)
        self.assertEqual(duty._closure, 'uncertain-state')
        with self.assertRaises(ValueError): duty.close()

    def test_SD12_terminal_close_state_never_allows_a_new_constructor(self):
        duty = source.OriginalSocket()
        duty.close()
        with patch.object(source.socket, 'socket') as factory:
            with self.assertRaises(ValueError): duty.acquire(4)
            factory.assert_not_called()
        self.assertTrue(duty._spent)
        self.assertEqual(duty._closure, 'returned-no-acquisition')
