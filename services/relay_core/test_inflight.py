"""Unit tests for the in-flight order registry."""

import threading

from relay_core.inflight import InFlightOrders


class TestInFlightOrders:
    def test_register_then_intersect(self) -> None:
        reg = InFlightOrders()
        reg.register("kraken", {"ORD1"})
        assert reg.intersect("kraken", {"ORD1", "ORD2"}) == {"ORD1"}

    def test_release_removes(self) -> None:
        reg = InFlightOrders()
        reg.register("kraken", {"ORD1"})
        reg.release("kraken", {"ORD1"})
        assert reg.intersect("kraken", {"ORD1"}) == set()

    def test_relay_namespaces_isolated(self) -> None:
        reg = InFlightOrders()
        reg.register("kraken", {"ORD1"})
        assert reg.intersect("ibkr", {"ORD1"}) == set()

    def test_counted_registration(self) -> None:
        """Two concurrent flushes of the same order both register; the
        order stays in flight until both release."""
        reg = InFlightOrders()
        reg.register("kraken", {"ORD1"})
        reg.register("kraken", {"ORD1"})
        reg.release("kraken", {"ORD1"})
        assert reg.intersect("kraken", {"ORD1"}) == {"ORD1"}
        reg.release("kraken", {"ORD1"})
        assert reg.intersect("kraken", {"ORD1"}) == set()

    def test_release_unknown_id_is_safe(self) -> None:
        reg = InFlightOrders()
        reg.release("kraken", {"NEVER-REGISTERED"})
        assert reg.intersect("kraken", {"NEVER-REGISTERED"}) == set()

    def test_multiple_orders_per_call(self) -> None:
        reg = InFlightOrders()
        reg.register("kraken", {"A", "B"})
        assert reg.intersect("kraken", {"A", "B", "C"}) == {"A", "B"}
        reg.release("kraken", {"A"})
        assert reg.intersect("kraken", {"A", "B", "C"}) == {"B"}

    def test_thread_safety_balanced_register_release(self) -> None:
        """Concurrent register/release pairs from many threads leave the
        registry empty — no lost updates, no negative counts."""
        reg = InFlightOrders()
        order_ids = [f"ORD{i}" for i in range(20)]

        def worker() -> None:
            for oid in order_ids:
                reg.register("kraken", {oid})
                reg.release("kraken", {oid})

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert reg.intersect("kraken", set(order_ids)) == set()
