"""Tests for the Kraken WebSocket v2 parser."""

import unittest
from typing import cast

from shared import BuySell

from .kraken_types import KrakenWsExecution, KrakenWsMessage
from .ws_parser import _extract_fee, _parse_fill, normalize_order_type, parse_executions

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_execution(**overrides: object) -> KrakenWsExecution:
    base: KrakenWsExecution = {
        "exec_type": "trade",
        "exec_id": "TXID-001",
        "order_id": "ORD-001",
        "symbol": "BTC/USD",
        "side": "buy",
        "order_type": "limit",
        "last_price": 65000.0,
        "last_qty": 0.1,
        "cost": 6500.0,
        "fees": [{"asset": "USD", "qty": 6.5}],
        "timestamp": "2026-04-12T10:00:00Z",
    }
    return cast(KrakenWsExecution, {**base, **overrides})


def _make_message(data: list[KrakenWsExecution]) -> KrakenWsMessage:
    return {"channel": "executions", "type": "snapshot", "data": data}


# ── normalize_order_type ──────────────────────────────────────────────────────


class TestNormalizeOrderType(unittest.TestCase):

    def test_market(self) -> None:
        self.assertEqual(normalize_order_type("market"), "market")

    def test_limit(self) -> None:
        self.assertEqual(normalize_order_type("limit"), "limit")

    def test_stop_loss(self) -> None:
        self.assertEqual(normalize_order_type("stop-loss"), "stop")

    def test_stop_loss_limit(self) -> None:
        self.assertEqual(normalize_order_type("stop-loss-limit"), "stop_limit")

    def test_trailing_stop(self) -> None:
        self.assertEqual(normalize_order_type("trailing-stop"), "trailing_stop")

    def test_trailing_stop_limit(self) -> None:
        self.assertEqual(normalize_order_type("trailing-stop-limit"), "trailing_stop")

    def test_unknown_returns_none(self) -> None:
        self.assertIsNone(normalize_order_type("iceberg"))

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(normalize_order_type(""))


# ── parse_executions ─────────────────────────────────────────────────────────


class TestParseExecutions(unittest.TestCase):

    def test_wrong_channel_returns_empty(self) -> None:
        msg: KrakenWsMessage = {"channel": "ticker", "data": []}
        fills, errors = parse_executions(msg)
        self.assertEqual(fills, [])
        self.assertEqual(errors, [])

    def test_missing_channel_returns_empty(self) -> None:
        msg: KrakenWsMessage = {}
        fills, errors = parse_executions(msg)
        self.assertEqual(fills, [])
        self.assertEqual(errors, [])

    def test_data_not_list_appends_error(self) -> None:
        msg = cast(KrakenWsMessage, {"channel": "executions", "data": "bad"})
        fills, errors = parse_executions(msg)
        self.assertEqual(fills, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("missing 'data' list", errors[0])

    def test_non_trade_exec_type_skipped(self) -> None:
        item = _make_execution(exec_type="pending_new")
        fills, errors = parse_executions(_make_message([item]))
        self.assertEqual(fills, [])
        self.assertEqual(errors, [])

    def test_non_dict_item_appends_error(self) -> None:
        msg = cast(KrakenWsMessage, {"channel": "executions", "data": ["not-a-dict"]})
        fills, errors = parse_executions(msg)
        self.assertEqual(fills, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("not a dict", errors[0])

    def test_valid_trade_returns_fill(self) -> None:
        item = _make_execution()
        fills, errors = parse_executions(_make_message([item]))
        self.assertEqual(len(fills), 1)
        self.assertEqual(errors, [])
        self.assertEqual(fills[0].execId, "TXID-001")
        self.assertEqual(fills[0].currency, "USD")

    def test_parse_error_appended_not_raised(self) -> None:
        item = _make_execution(side="invalid_side")
        fills, errors = parse_executions(_make_message([item]))
        self.assertEqual(fills, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("TXID-001", errors[0])

    def test_mixed_items_partial_success(self) -> None:
        good = _make_execution(exec_id="GOOD-1")
        bad = _make_execution(exec_id="BAD-1", side="??")
        skipped = _make_execution(exec_id="SKIP-1", exec_type="cancelled")
        fills, errors = parse_executions(_make_message([good, bad, skipped]))
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0].execId, "GOOD-1")
        self.assertEqual(len(errors), 1)
        self.assertIn("BAD-1", errors[0])

    def test_empty_data_list_returns_empty(self) -> None:
        fills, errors = parse_executions(_make_message([]))
        self.assertEqual(fills, [])
        self.assertEqual(errors, [])


# ── _parse_fill ───────────────────────────────────────────────────────────────


class TestParseFill(unittest.TestCase):

    def test_fields_mapped_correctly(self) -> None:
        fill = _parse_fill(_make_execution())
        self.assertEqual(fill.execId, "TXID-001")
        self.assertEqual(fill.orderId, "ORD-001")
        self.assertEqual(fill.symbol, "BTC/USD")
        self.assertEqual(fill.assetClass, "crypto")
        self.assertEqual(fill.price, 65000.0)
        self.assertEqual(fill.volume, 0.1)
        # Fixture is a BUY → positive volume, negative cost.
        self.assertEqual(fill.cost, -6500.0)
        self.assertEqual(fill.timestamp, "2026-04-12T10:00:00")
        self.assertEqual(fill.source, "ws_execution")

    def test_buy_side(self) -> None:
        fill = _parse_fill(_make_execution(side="buy"))
        self.assertEqual(fill.side, BuySell.BUY)

    def test_sell_side(self) -> None:
        fill = _parse_fill(_make_execution(side="sell"))
        self.assertEqual(fill.side, BuySell.SELL)

    def test_invalid_side_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_fill(_make_execution(side="short"))

    def test_order_type_mapped(self) -> None:
        fill = _parse_fill(_make_execution(order_type="stop-loss"))
        self.assertEqual(fill.orderType, "stop")

    def test_unknown_order_type_is_none(self) -> None:
        fill = _parse_fill(_make_execution(order_type="algo"))
        self.assertIsNone(fill.orderType)

    def test_fee_single_asset_summed(self) -> None:
        item = _make_execution(fees=[
            {"asset": "USD", "qty": 3.0},
            {"asset": "USD", "qty": 1.5},
        ])
        fill = _parse_fill(item)
        self.assertAlmostEqual(fill.fee, 4.5)

    def test_fee_mixed_assets_returns_zero(self) -> None:
        # Summing USD + BTC fees produces a meaningless scalar; return 0.0.
        item = _make_execution(fees=[
            {"asset": "USD", "qty": 3.0},
            {"asset": "BTC", "qty": 1.5},
        ])
        fill = _parse_fill(item)
        self.assertAlmostEqual(fill.fee, 0.0)

    def test_fee_is_absolute_value(self) -> None:
        item = _make_execution(fees=[{"asset": "USD", "qty": -2.0}])
        fill = _parse_fill(item)
        self.assertAlmostEqual(fill.fee, 2.0)

    def test_no_fees_field_defaults_to_zero(self) -> None:
        item: KrakenWsExecution = {
            "exec_id": "X",
            "order_id": "O",
            "symbol": "ETH/USD",
            "side": "buy",
            "order_type": "market",
            "last_price": 1.0,
            "last_qty": 1.0,
            "cost": 1.0,
            "timestamp": "2026-04-12T10:00:00Z",
        }
        fill = _parse_fill(item)
        self.assertEqual(fill.fee, 0.0)

    def test_empty_fees_list_gives_zero(self) -> None:
        fill = _parse_fill(_make_execution(fees=[]))
        self.assertEqual(fill.fee, 0.0)

    def test_fee_usd_equiv_takes_priority(self) -> None:
        # fee_usd_equiv should be used even when fees[] is present.
        item = _make_execution(
            fee_usd_equiv=9.99,
            fees=[{"asset": "USD", "qty": 3.0}],
        )
        fill = _parse_fill(item)
        self.assertAlmostEqual(fill.fee, 9.99)

    def test_fee_usd_equiv_negative_is_absolute(self) -> None:
        item = _make_execution(fee_usd_equiv=-5.0)
        fill = _parse_fill(item)
        self.assertAlmostEqual(fill.fee, 5.0)


# ── _extract_fee ──────────────────────────────────────────────────────────────


class TestExtractFee(unittest.TestCase):

    def test_fee_usd_equiv_wins_over_fees_array(self) -> None:
        item = _make_execution(fee_usd_equiv=7.0, fees=[{"asset": "USD", "qty": 3.0}])
        self.assertAlmostEqual(_extract_fee(item), 7.0)

    def test_fee_usd_equiv_negative_returned_as_absolute(self) -> None:
        item = _make_execution(fee_usd_equiv=-4.5)
        self.assertAlmostEqual(_extract_fee(item), 4.5)

    def test_single_asset_entries_summed(self) -> None:
        item = _make_execution(fees=[
            {"asset": "USD", "qty": 2.0},
            {"asset": "USD", "qty": 1.0},
        ])
        self.assertAlmostEqual(_extract_fee(item), 3.0)

    def test_single_asset_negative_qty_abs_per_entry(self) -> None:
        # abs(-5) + abs(3) = 8, not abs(-5 + 3) = 2
        item = _make_execution(fees=[
            {"asset": "USD", "qty": -5.0},
            {"asset": "USD", "qty": 3.0},
        ])
        self.assertAlmostEqual(_extract_fee(item), 8.0)

    def test_mixed_assets_returns_zero(self) -> None:
        item = _make_execution(fees=[
            {"asset": "USD", "qty": 3.0},
            {"asset": "BTC", "qty": 1.5},
        ])
        self.assertAlmostEqual(_extract_fee(item), 0.0)

    def test_empty_fees_list_returns_zero(self) -> None:
        self.assertAlmostEqual(_extract_fee(_make_execution(fees=[])), 0.0)

    def test_no_fees_field_returns_zero(self) -> None:
        item = cast(KrakenWsExecution, {
            "exec_id": "X", "order_id": "O", "side": "buy",
            "last_price": 1.0, "last_qty": 1.0, "cost": 1.0,
        })
        self.assertAlmostEqual(_extract_fee(item), 0.0)


    def test_raw_contains_original_item(self) -> None:
        item = _make_execution()
        fill = _parse_fill(item)
        self.assertEqual(fill.raw["exec_id"], "TXID-001")
        self.assertEqual(fill.raw["symbol"], "BTC/USD")
