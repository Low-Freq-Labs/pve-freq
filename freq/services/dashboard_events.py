"""In-memory dashboard event publication shared by serve and API consumers."""

import queue
import threading
import time

from freq.services import dashboard_state

_sse_clients: list = []
_sse_lock = threading.Lock()


def _sse_subscribe() -> queue.Queue:
    """Register a new SSE client and return its bounded event queue."""
    client = queue.Queue(maxsize=50)
    with _sse_lock:
        _sse_clients.append(client)
    return client


def _sse_unsubscribe(client: queue.Queue):
    """Remove an SSE client queue, ignoring an already-absent client."""
    with _sse_lock:
        try:
            _sse_clients.remove(client)
        except ValueError:
            pass


def _sse_broadcast(event_type: str, data: dict):
    """Push one event object to every client, dropping full clients.

    Must not be called while holding the dashboard background-cache lock.
    """
    message = {"type": event_type, "data": data}
    dead = []
    with _sse_lock:
        for client in _sse_clients:
            try:
                client.put_nowait(message)
            except queue.Full:
                dead.append(client)
        for client in dead:
            try:
                _sse_clients.remove(client)
            except ValueError:
                pass


def _activity_add(event_type: str, message: str, detail: str = "", severity: str = "info"):
    """Record an activity event and publish the same object to SSE clients."""
    entry = {
        "ts": time.time(),
        "type": event_type,
        "message": message,
        "detail": detail,
        "severity": severity,
    }
    with dashboard_state.activity_lock:
        dashboard_state.activity_feed.appendleft(entry)
    _sse_broadcast("activity", entry)
