"""UNRUN negative DATA projection of the internal cleanup method ONLY.

This deliberately supplies a model self and replaces the auth module token
map. It is NOT OriginalAuthCommit construction, original gates/authentication,
an original issued-session graph or a logout/ACK test. The canonical pending
installation stays inactive/native-currentFalse. Results can earn only the
named modeled row/snapshot/control-flow credit, never AR12/native acceptance.
Execute only inside a separately reviewed qualified offline packet.
"""
import inspect
import sys
import types
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from freq.api import auth
from freq.services.cluster_pilot_startup import OriginalPilotInstallation
from freq.services.cluster_references import TargetSnapshot, _Reference
from freq.services.pilot_auth_commit import OriginalAuthCommit


class Cancel(BaseException):
    pass


@contextmanager
def inject_cleanup_line(needle, records, error, key=None):
    """Raise once at the exact original method line, inside its own try.

    Real builtin dicts remain real dicts: a fake mapping must not fail a type
    guard before reaching the intended row/snapshot boundary. The trace hook
    is explicit modeled instrumentation, not unmodified whole-path evidence.
    """
    method = OriginalAuthCommit._retire_session_locked
    lines, first_line = inspect.getsourcelines(method)
    selected = [first_line + i for i, text in enumerate(lines)
                if text.strip() == needle]
    if len(selected) != 1:
        raise AssertionError('fixture source line is not unique')
    hits = []
    old_trace = sys.gettrace()
    if old_trace is not None:
        raise AssertionError('fixture refuses an ambient trace hook')
    def trace(frame, event, arg):
        if (event == 'line' and frame.f_code is method.__code__ and
                frame.f_lineno == selected[0] and
                frame.f_locals.get('records') is records and
                (key is None or frame.f_locals.get('key') == key)):
            hits.append(True)
            raise error
        return trace
    sys.settrace(trace)
    try:
        yield hits
    finally:
        sys.settrace(old_trace)
    if len(hits) != 1:
        raise AssertionError('intended DATA failure boundary was not reached once')


class AuthRetirementDataProjection(unittest.TestCase):
    def setUp(self):
        self.owner = OriginalPilotInstallation()
        self.owner._prepare_pending_original()
        self.session, self.other = {}, {}
        self.token = 'fictional-token'
        self.target = TargetSnapshot('fictional-revision', 'fictional-node', '192.0.2.1')
        self.references = types.SimpleNamespace(_selections={}, _bindings={})
        self.broker = types.SimpleNamespace(_live=False)
        self.model = types.SimpleNamespace(_installation=self.owner,
            _references=self.references, _broker=self.broker)
        self.model._uncertain = types.MethodType(OriginalAuthCommit._uncertain, self.model)
        # Explicit model attachment ONLY: no auth component constructor or
        # native/source/writer/currentness gate has been supplied or bypassed
        # to admit anything. No public transaction is called.
        self.owner._auth_commit = self.model
        self.owner._issued_sessions[self.token] = self.session
        self.owner._issued_sessions['unrelated'] = self.other
        self.tokens = {self.token: self.session, 'unrelated': self.other}
        changed = patch.object(auth, '_auth_tokens', self.tokens)
        changed.start()
        self.addCleanup(changed.stop)

    def add_rows(self, table, malformed=False):
        if malformed:
            table['0' * 32] = object()
        table['1' * 32] = _Reference(self.session, self.target, 130.0)
        table['2' * 32] = _Reference(self.other, self.target, 130.0)
        table['3' * 32] = _Reference(self.session, self.target, 130.0)

    def retire_projection(self):
        return OriginalAuthCommit._retire_session_locked(self.model,
                                                         self.token, self.session)

    def assert_auth_duties(self):
        self.assertNotIn(self.token, self.tokens)
        self.assertNotIn(self.token, self.owner._issued_sessions)
        self.assertIs(self.tokens['unrelated'], self.other)
        self.assertIs(self.owner._issued_sessions['unrelated'], self.other)
        self.assertFalse(self.owner._live)
        self.assertFalse(self.owner._native_current_locked(object()))

    def test_AM01_bad_selection_row_does_not_skip_later_known_rows(self):
        self.add_rows(self.references._selections, malformed=True)
        self.add_rows(self.references._bindings)
        with self.assertRaises(Exception):
            self.retire_projection()
        self.assertEqual(set(self.references._selections), {'0' * 32, '2' * 32})
        self.assertEqual(set(self.references._bindings), {'2' * 32})
        self.assertTrue(self.owner._admission_uncertain)
        self.assert_auth_duties()

    def test_AM02_bad_binding_row_does_not_skip_later_known_rows(self):
        self.add_rows(self.references._selections)
        self.add_rows(self.references._bindings, malformed=True)
        with self.assertRaises(Exception):
            self.retire_projection()
        self.assertEqual(set(self.references._selections), {'2' * 32})
        self.assertEqual(set(self.references._bindings), {'0' * 32, '2' * 32})
        self.assert_auth_duties()

    def test_AM03_row_control_retained_and_later_duties_attempted(self):
        self.add_rows(self.references._selections)
        self.add_rows(self.references._bindings)
        control = Cancel('fictional row cancellation')
        with inject_cleanup_line('del records[key]', self.references._selections,
                                  control, '1' * 32):
            with self.assertRaises(Cancel) as caught:
                self.retire_projection()
        self.assertIs(caught.exception, control)
        self.assertEqual(set(self.references._selections), {'1' * 32, '2' * 32})
        self.assertEqual(set(self.references._bindings), {'2' * 32})
        self.assert_auth_duties()

    def test_AM04_first_snapshot_failure_still_attempts_other_table(self):
        self.add_rows(self.references._selections)
        self.add_rows(self.references._bindings)
        failure = MemoryError('fictional selection snapshot failure')
        with inject_cleanup_line('rows = tuple(records.items())',
                                  self.references._selections, failure):
            with self.assertRaises(MemoryError) as caught:
                self.retire_projection()
        self.assertIs(caught.exception, failure)
        self.assertEqual(set(self.references._selections), {'1' * 32, '2' * 32, '3' * 32})
        self.assertEqual(set(self.references._bindings), {'2' * 32})
        self.assert_auth_duties()

    def test_AM05_second_snapshot_failure_preserves_completed_first(self):
        self.add_rows(self.references._selections)
        self.add_rows(self.references._bindings)
        failure = MemoryError('fictional binding snapshot failure')
        with inject_cleanup_line('rows = tuple(records.items())',
                                  self.references._bindings, failure):
            with self.assertRaises(MemoryError) as caught:
                self.retire_projection()
        self.assertIs(caught.exception, failure)
        self.assertEqual(set(self.references._selections), {'2' * 32})
        self.assertEqual(set(self.references._bindings), {'1' * 32, '2' * 32, '3' * 32})
        self.assert_auth_duties()

    def test_AM06_later_genuine_control_outranks_ordinary_failure(self):
        self.add_rows(self.references._selections, malformed=True)
        self.add_rows(self.references._bindings)
        control = Cancel('fictional later control')
        with inject_cleanup_line('del records[key]', self.references._bindings,
                                  control, '1' * 32):
            with self.assertRaises(Cancel) as caught:
                self.retire_projection()
        self.assertIs(caught.exception, control)
        self.assertNotIn('3' * 32, self.references._bindings)
        self.assert_auth_duties()

    def test_AM07_malformed_key_does_not_skip_valid_legacy_rows(self):
        self.references._selections['bad-key'] = _Reference(self.session, self.target, 130.0)
        self.add_rows(self.references._selections)
        with self.assertRaises(Exception):
            self.retire_projection()
        self.assertEqual(set(self.references._selections), {'bad-key', '2' * 32})
        self.assert_auth_duties()

    def test_AM08_successful_DATA_cleanup_still_grants_no_logout_ACK(self):
        self.add_rows(self.references._selections)
        self.add_rows(self.references._bindings)
        self.retire_projection()
        self.assertEqual(set(self.references._selections), {'2' * 32})
        self.assertEqual(set(self.references._bindings), {'2' * 32})
        self.assert_auth_duties()
        self.assertIsNone(self.owner._server)
        self.assertIsNone(self.owner._gate)
        self.assertFalse(self.broker._live)


if __name__ == '__main__':
    unittest.main(verbosity=2)
