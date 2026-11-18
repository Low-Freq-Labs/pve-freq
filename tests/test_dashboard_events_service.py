"""Behavior and consumer contracts for the dashboard event service."""

import queue
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.case_matrix import run_case_matrix  # noqa: E402, I001

from freq.api import vm
from freq.modules import serve
from freq.services import dashboard_events, dashboard_state


class _ExplodingClient:
    def put_nowait(self, _message):
        raise RuntimeError("delivery exploded")


class _EqualityExplodes:
    def __eq__(self, _other):
        raise RuntimeError("equality exploded")


class DashboardEventServiceTests(unittest.TestCase):
    def setUp(self):
        with dashboard_events._sse_lock:
            dashboard_events._sse_clients.clear()
        with dashboard_state.activity_lock:
            self._activity_snapshot = list(dashboard_state.activity_feed)
            dashboard_state.activity_feed.clear()

    def tearDown(self):
        with dashboard_events._sse_lock:
            dashboard_events._sse_clients.clear()
        with dashboard_state.activity_lock:
            dashboard_state.activity_feed.clear()
            dashboard_state.activity_feed.extend(self._activity_snapshot)

    def _case_serve_aliases_are_exact_service_objects(self):
        for name in (
            "_sse_clients",
            "_sse_lock",
            "_sse_subscribe",
            "_sse_unsubscribe",
            "_sse_broadcast",
            "_activity_add",
        ):
            self.assertIs(getattr(serve, name), getattr(dashboard_events, name))
        self.assertIs(vm._sse_broadcast, dashboard_events._sse_broadcast)
        self.assertIs(dashboard_events.dashboard_state.activity_feed, dashboard_state.activity_feed)
        self.assertIs(dashboard_events.dashboard_state.activity_lock, dashboard_state.activity_lock)

    def _case_subscribe_uses_bounded_queue_and_shared_list_lock(self):
        client = dashboard_events._sse_subscribe()
        self.assertIsInstance(client, queue.Queue)
        self.assertEqual(client.maxsize, 50)
        with dashboard_events._sse_lock:
            self.assertEqual(dashboard_events._sse_clients, [client])

    def _case_unsubscribe_removes_once_and_missing_is_safe(self):
        client = dashboard_events._sse_subscribe()
        self.assertIsNone(dashboard_events._sse_unsubscribe(client))
        self.assertIsNone(dashboard_events._sse_unsubscribe(client))
        self.assertNotIn(client, dashboard_events._sse_clients)

    def _case_unsubscribe_propagates_non_value_error(self):
        dashboard_events._sse_clients.append(_EqualityExplodes())
        with self.assertRaisesRegex(RuntimeError, "equality exploded"):
            dashboard_events._sse_unsubscribe(object())

    def _case_broadcast_shares_message_and_data_in_registration_order(self):
        first = dashboard_events._sse_subscribe()
        second = dashboard_events._sse_subscribe()
        data = {"key": "health"}

        self.assertIsNone(dashboard_events._sse_broadcast("cache_update", data))

        first_message = first.get_nowait()
        second_message = second.get_nowait()
        self.assertIs(first_message, second_message)
        self.assertIs(first_message["data"], data)
        self.assertEqual(list(first_message), ["type", "data"])

    def _case_full_client_is_removed_after_later_healthy_delivery(self):
        full = dashboard_events._sse_subscribe()
        healthy = dashboard_events._sse_subscribe()
        for index in range(50):
            full.put_nowait(index)

        dashboard_events._sse_broadcast("cache_update", {"key": "fleet_overview"})

        self.assertNotIn(full, dashboard_events._sse_clients)
        self.assertEqual(healthy.get_nowait()["type"], "cache_update")

    def _case_non_full_error_interrupts_deferred_dead_cleanup(self):
        full = dashboard_events._sse_subscribe()
        for index in range(50):
            full.put_nowait(index)
        exploding = _ExplodingClient()
        dashboard_events._sse_clients.append(exploding)

        with self.assertRaisesRegex(RuntimeError, "delivery exploded"):
            dashboard_events._sse_broadcast("cache_update", {})

        self.assertIn(full, dashboard_events._sse_clients)
        self.assertIn(exploding, dashboard_events._sse_clients)

    def _case_broadcast_without_clients_returns_none(self):
        self.assertIsNone(dashboard_events._sse_broadcast("test", {"ok": True}))

    def _case_activity_add_time_order_identity_and_unlocked_broadcast(self):
        published = []

        def capture(event_type, entry):
            acquired = dashboard_state.activity_lock.acquire(blocking=False)
            self.assertTrue(acquired)
            dashboard_state.activity_lock.release()
            published.append((event_type, entry))

        with (
            patch.object(dashboard_events.time, "time", return_value=123.5) as clock,
            patch.object(dashboard_events, "_sse_broadcast", side_effect=capture),
        ):
            result = dashboard_events._activity_add("vm_state", "changed", "VMID 100", "warning")

        self.assertIsNone(result)
        clock.assert_called_once_with()
        entry = dashboard_state.activity_feed[0]
        self.assertEqual(list(entry), ["ts", "type", "message", "detail", "severity"])
        self.assertEqual(entry, {
            "ts": 123.5,
            "type": "vm_state",
            "message": "changed",
            "detail": "VMID 100",
            "severity": "warning",
        })
        self.assertEqual(published[0][0], "activity")
        self.assertIs(published[0][1], entry)

    def _case_activity_feed_mutation_survives_broadcast_failure(self):
        with (
            patch.object(dashboard_events.time, "time", return_value=77),
            patch.object(dashboard_events, "_sse_broadcast", side_effect=RuntimeError("boom")),
            self.assertRaisesRegex(RuntimeError, "boom"),
        ):
            dashboard_events._activity_add("probe", "failed")

        self.assertEqual(dashboard_state.activity_feed[0]["ts"], 77)
        self.assertEqual(dashboard_state.activity_feed[0]["message"], "failed")


DASHBOARD_EVENT_SERVICE_CASES = (
    "_case_serve_aliases_are_exact_service_objects",
    "_case_subscribe_uses_bounded_queue_and_shared_list_lock",
    "_case_unsubscribe_removes_once_and_missing_is_safe",
    "_case_unsubscribe_propagates_non_value_error",
    "_case_broadcast_shares_message_and_data_in_registration_order",
    "_case_full_client_is_removed_after_later_healthy_delivery",
    "_case_non_full_error_interrupts_deferred_dead_cleanup",
    "_case_broadcast_without_clients_returns_none",
    "_case_activity_add_time_order_identity_and_unlocked_broadcast",
    "_case_activity_feed_mutation_survives_broadcast_failure",
)


class TestDashboardEventServiceMatrix(unittest.TestCase):
    def test_dashboard_event_service_matrix(self):
        run_case_matrix(self, DashboardEventServiceTests, DASHBOARD_EVENT_SERVICE_CASES)


class VmDashboardEventConsumerTests(unittest.TestCase):
    def setUp(self):
        with vm._bg_lock:
            self._fleet_snapshot = vm._bg_cache.get("fleet_overview")
            self._timestamp_snapshot = vm._bg_cache_ts.get("fleet_overview")

    def tearDown(self):
        with vm._bg_lock:
            vm._bg_cache["fleet_overview"] = self._fleet_snapshot
            vm._bg_cache_ts["fleet_overview"] = self._timestamp_snapshot

    def _seed_fleet(self):
        with vm._bg_lock:
            vm._bg_cache["fleet_overview"] = {
                "vms": [
                    {"vmid": 100, "status": "stopped", "category": "production"},
                    {"vmid": 101, "status": "running", "category": "production"},
                    {"vmid": 9000, "status": "stopped", "category": "templates"},
                ],
                "summary": {"running": 1, "stopped": 1},
            }

    def test_vm_patch_broadcasts_after_unlock_in_exact_order(self):
        self._seed_fleet()
        events = []

        def capture(event_type, payload):
            acquired = vm._bg_lock.acquire(blocking=False)
            self.assertTrue(acquired)
            vm._bg_lock.release()
            events.append((event_type, payload))

        with patch("freq.api.vm._sse_broadcast", side_effect=capture):
            vm._patch_fleet_overview_vm_status(100, "running")

        self.assertEqual([event[0] for event in events], ["cache_update", "vm_state"])
        self.assertEqual(events[0][1]["key"], "fleet_overview")
        self.assertEqual(events[1][1], {"vmid": 100, "new": "running"})
        self.assertEqual(vm._bg_cache["fleet_overview"]["summary"], {"running": 2, "stopped": 0})

    def test_vm_patch_swallows_first_broadcast_failure_and_skips_second(self):
        self._seed_fleet()
        with patch("freq.api.vm._sse_broadcast", side_effect=RuntimeError("boom")) as broadcast:
            vm._patch_fleet_overview_vm_status(100, "running")
        broadcast.assert_called_once()
        self.assertEqual(vm._bg_cache["fleet_overview"]["vms"][0]["status"], "running")

    def test_vm_patch_early_returns_emit_no_events(self):
        self._seed_fleet()
        with patch("freq.api.vm._sse_broadcast") as broadcast:
            vm._patch_fleet_overview_vm_status(100, "paused")
            vm._patch_fleet_overview_vm_status(999, "running")
            with vm._bg_lock:
                vm._bg_cache["fleet_overview"] = None
            vm._patch_fleet_overview_vm_status(100, "running")
        broadcast.assert_not_called()


if __name__ == "__main__":
    unittest.main()
