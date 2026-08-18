"""In-flight order registry — shrinks the listener/poller duplicate window.

Nothing is written to the dedup DB until ``notify()`` succeeds
(mark-after-notify), so while the listener is mid-notify — which can take
``attempts x read-timeout`` against a slow receiver — a concurrent poll
cycle sees the same fills as unprocessed and sends a duplicate webhook.

The listener registers its orderIds here for the duration of notify+mark;
the poller defers any fill whose order is currently registered to its next
cycle. Registration is counted (not exclusive): two concurrent listener
flushes for the same order are legitimate distinct fill batches and must
both proceed.

Deliberately one-directional (listener registers, poller checks), never
the reverse: WS events precede REST visibility by the settlement lag, so
listener-first is the realistic ordering — and only the poller can defer
safely, since its fills reappear next cycle while a listener event is
consumed once. The residual reverse race (WS event landing mid-poller-
notify) is covered by exec-id dedup once the poller marks, and by
consumer-side dedup otherwise.

This guard is advisory and best-effort — it shrinks the duplicate window
from tens of seconds to the microseconds between the poller's check and
its notify. Consumer-side dedup on ``deliveryId``/``orderId`` remains the
backstop, as delivery is at-least-once by design.

Both engines dispatch from ``asyncio.to_thread`` workers, so the registry
is guarded by a ``threading.Lock`` (never an ``asyncio.Lock``).
"""

import threading
from collections.abc import Iterable


class InFlightOrders:
    """Process-wide, thread-safe multiset of orders currently being notified."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}

    @staticmethod
    def _key(relay_name: str, order_id: str) -> str:
        return f"{relay_name}:{order_id}"

    def register(self, relay_name: str, order_ids: Iterable[str]) -> None:
        """Mark orders as in flight. Pair every call with ``release`` in a finally."""
        with self._lock:
            for oid in order_ids:
                key = self._key(relay_name, oid)
                self._counts[key] = self._counts.get(key, 0) + 1

    def release(self, relay_name: str, order_ids: Iterable[str]) -> None:
        """Undo one ``register`` for each order. Safe on unknown ids."""
        with self._lock:
            for oid in order_ids:
                key = self._key(relay_name, oid)
                count = self._counts.get(key, 0)
                if count <= 1:
                    self._counts.pop(key, None)
                else:
                    self._counts[key] = count - 1

    def intersect(self, relay_name: str, order_ids: Iterable[str]) -> set[str]:
        """Return the subset of *order_ids* currently in flight for *relay_name*."""
        with self._lock:
            return {
                oid for oid in order_ids
                if self._key(relay_name, oid) in self._counts
            }


# Singleton shared by the listener and poller engines within one process.
INFLIGHT_ORDERS = InFlightOrders()
