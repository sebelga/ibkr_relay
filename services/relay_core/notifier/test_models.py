"""Unit tests for outbound payload contracts — deliveryId semantics."""

from typing import Any

from relay_core.notifier.models import WebhookPayloadTrades, compute_delivery_id
from shared import BuySell, Trade


def _make_trade(**overrides: Any) -> Trade:
    defaults: dict[str, Any] = {
        "source": "rest_poll",
        "symbol": "USDTEUR",
        "assetClass": "crypto",
        "side": BuySell.SELL,
        "volume": 100.0,
        "price": 0.86,
        "cost": 86.0,
        "fee": 0.1,
        "orderId": "OPX5ZK",
        "timestamp": "2026-08-16T17:36:06",
        "execIds": ["T7NQDE"],
        "fillCount": 1,
        "raw": {},
    }
    defaults.update(overrides)
    return Trade(**defaults)


class TestComputeDeliveryId:
    def test_deterministic_across_constructions(self) -> None:
        """Re-sending the same trades (retry, next-cycle re-send) must
        produce the identical deliveryId — receivers dedupe on it."""
        a = WebhookPayloadTrades(relay="kraken", data=[_make_trade()], errors=[])
        b = WebhookPayloadTrades(relay="kraken", data=[_make_trade()], errors=[])
        assert a.deliveryId == b.deliveryId

    def test_auto_computed_and_shaped(self) -> None:
        payload = WebhookPayloadTrades(relay="kraken", data=[_make_trade()], errors=[])
        assert payload.deliveryId
        assert len(payload.deliveryId) == 16
        int(payload.deliveryId, 16)  # hex

    def test_differs_by_relay(self) -> None:
        a = WebhookPayloadTrades(relay="kraken", data=[_make_trade()], errors=[])
        b = WebhookPayloadTrades(relay="ibkr", data=[_make_trade()], errors=[])
        assert a.deliveryId != b.deliveryId

    def test_differs_by_exec_ids(self) -> None:
        a = WebhookPayloadTrades(
            relay="kraken", data=[_make_trade(execIds=["T1"])], errors=[],
        )
        b = WebhookPayloadTrades(
            relay="kraken", data=[_make_trade(execIds=["T2"])], errors=[],
        )
        assert a.deliveryId != b.deliveryId

    def test_independent_of_trade_order(self) -> None:
        t1 = _make_trade(orderId="O1", execIds=["A"])
        t2 = _make_trade(orderId="O2", execIds=["B"])
        a = WebhookPayloadTrades(relay="kraken", data=[t1, t2], errors=[])
        b = WebhookPayloadTrades(relay="kraken", data=[t2, t1], errors=[])
        assert a.deliveryId == b.deliveryId

    def test_independent_of_trade_values(self) -> None:
        """Identity comes from orderId/execIds, never from price/volume —
        a listener re-send with a settled fee must keep the same ID."""
        a = WebhookPayloadTrades(
            relay="kraken", data=[_make_trade(fee=0.0)], errors=[],
        )
        b = WebhookPayloadTrades(
            relay="kraken", data=[_make_trade(fee=1.23)], errors=[],
        )
        assert a.deliveryId == b.deliveryId

    def test_provided_value_preserved_on_round_trip(self) -> None:
        original = WebhookPayloadTrades(
            relay="kraken", data=[_make_trade()], errors=[],
        )
        round_tripped = WebhookPayloadTrades.model_validate_json(
            original.model_dump_json(),
        )
        assert round_tripped.deliveryId == original.deliveryId

    def test_error_only_payload_hashes_errors(self) -> None:
        a = WebhookPayloadTrades(relay="kraken", data=[], errors=["bad row 1"])
        b = WebhookPayloadTrades(relay="kraken", data=[], errors=["bad row 2"])
        assert a.deliveryId != b.deliveryId

    def test_errors_do_not_affect_id_when_trades_present(self) -> None:
        """Parse/fx errors vary between the listener attempt and the poller
        re-send of the same trades — they must not change the identity."""
        a = WebhookPayloadTrades(relay="kraken", data=[_make_trade()], errors=[])
        b = WebhookPayloadTrades(
            relay="kraken", data=[_make_trade()], errors=["fx lookup failed"],
        )
        assert a.deliveryId == b.deliveryId

    def test_helper_matches_model(self) -> None:
        trade = _make_trade()
        payload = WebhookPayloadTrades(relay="kraken", data=[trade], errors=[])
        assert payload.deliveryId == compute_delivery_id("kraken", [trade], [])


class TestJsonContract:
    def test_delivery_id_serialized(self) -> None:
        payload = WebhookPayloadTrades(relay="kraken", data=[_make_trade()], errors=[])
        assert f'"deliveryId": "{payload.deliveryId}"' in payload.model_dump_json(indent=2)

    def test_delivery_id_required_in_schema(self) -> None:
        """The Python-side default must not leak into the contract — TS
        consumers rely on deliveryId always being present."""
        schema = WebhookPayloadTrades.model_json_schema()
        assert "deliveryId" in schema["required"]
        assert "relay" in schema["required"]
        assert "type" in schema["required"]
