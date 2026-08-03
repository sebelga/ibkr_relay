"""Unit tests for the signed-delta convention on Fill and Trade.

The convention (documented on ``shared.models.Fill``) is a public contract:

    volume  buy > 0, sell < 0   — position delta
    cost    buy < 0, sell > 0   — cash delta (opposite sign to volume)
    fee     always > 0          — a debit either way
    price   always > 0          — magnitude, never signed

Enforcement lives in a model validator rather than in the adapters, so
these tests are the authoritative statement of the contract. They feed in
each broker's *native* convention and assert the canonical output.
"""

import pytest

from shared import BuySell, Fill, Trade, aggregate_fills


def _fill(side: BuySell, volume: float, cost: float, fee: float = 1.5) -> Fill:
    return Fill(
        execId="e1",
        orderId="o1",
        symbol="TEST",
        assetClass="equity",
        side=side,
        price=100.0,
        volume=volume,
        cost=cost,
        fee=fee,
        timestamp="2026-07-24T13:55:51",
        source="flex",
        currency="USD",
        raw={},
    )


def _trade(side: BuySell, volume: float, cost: float, fee: float = 1.5) -> Trade:
    return Trade(
        orderId="o1",
        symbol="TEST",
        assetClass="equity",
        side=side,
        price=100.0,
        volume=volume,
        cost=cost,
        fee=fee,
        fillCount=1,
        execIds=["e1"],
        timestamp="2026-07-24T13:55:51",
        source="flex",
        currency="USD",
        raw={},
    )


# ── Canonical output, whatever the broker sends ──────────────────────

class TestVolumeSign:
    def test_buy_is_positive(self) -> None:
        assert _fill(BuySell.BUY, 25.0, 4903.0).volume == 25.0

    def test_sell_is_negative(self) -> None:
        assert _fill(BuySell.SELL, 25.0, 4903.0).volume == -25.0

    def test_buy_from_negative_input_is_corrected(self) -> None:
        """A broker sending a negative magnitude on a buy is re-signed."""
        assert _fill(BuySell.BUY, -25.0, 4903.0).volume == 25.0

    def test_sell_from_negative_input_stays_negative(self) -> None:
        """IBKR Flex already signs sells negative — must be idempotent."""
        assert _fill(BuySell.SELL, -25.0, 4903.0).volume == -25.0


class TestCostSign:
    def test_buy_is_negative(self) -> None:
        """Buying spends money → negative cash delta."""
        assert _fill(BuySell.BUY, 25.0, 4903.0).cost == -4903.0

    def test_sell_is_positive(self) -> None:
        """Selling receives money → positive cash delta."""
        assert _fill(BuySell.SELL, 25.0, 4903.0).cost == 4903.0

    def test_flex_cost_basis_sign_is_inverted(self) -> None:
        """IBKR Flex reports `cost` as a cost-basis delta (buy +, sell -),
        the opposite of our cash delta. Both directions must flip."""
        assert _fill(BuySell.BUY, 25.0, 4903.0).cost == -4903.0
        assert _fill(BuySell.SELL, -25.0, -4903.0).cost == 4903.0

    def test_is_idempotent_under_revalidation(self) -> None:
        """Re-validating an already-canonical model must not flip signs."""
        once = _fill(BuySell.SELL, 25.0, 4903.0)
        twice = Fill.model_validate(once.model_dump())
        assert (twice.volume, twice.cost) == (once.volume, once.cost)
        assert (twice.volume, twice.cost) == (-25.0, 4903.0)


class TestFeeAndPrice:
    def test_fee_positive_on_buy(self) -> None:
        assert _fill(BuySell.BUY, 25.0, 4903.0, fee=-1.106).fee == 1.106

    def test_fee_positive_on_sell(self) -> None:
        """IBKR reports commissions as negative — never forward that."""
        assert _fill(BuySell.SELL, 25.0, 4903.0, fee=-1.106).fee == 1.106

    def test_price_is_never_signed(self) -> None:
        """Direction lives on volume/cost only; signing price too would
        double-count it and corrupt the VWAP weighting."""
        assert _fill(BuySell.SELL, 25.0, 4903.0).price == 100.0


class TestZeroHandling:
    def test_zero_volume_is_positive_zero_on_sell(self) -> None:
        """`-abs(0.0)` is `-0.0`, which serialises to "-0.0" and reads as a
        bug downstream. Both zeros must normalise to +0.0."""
        fill = _fill(BuySell.SELL, 0.0, 0.0)
        assert str(fill.volume) == "0.0"
        assert str(fill.cost) == "0.0"

    def test_zero_cost_is_positive_zero_on_buy(self) -> None:
        fill = _fill(BuySell.BUY, 10.0, 0.0)
        assert str(fill.cost) == "0.0"

    def test_zero_survives_json_round_trip(self) -> None:
        assert '"volume":0.0' in _fill(BuySell.SELL, 0.0, 0.0).model_dump_json()


class TestTradeCarriesConvention:
    def test_sell_trade_is_signed(self) -> None:
        trade = _trade(BuySell.SELL, 25.0, 4903.0)
        assert (trade.volume, trade.cost) == (-25.0, 4903.0)

    def test_buy_trade_is_signed(self) -> None:
        trade = _trade(BuySell.BUY, 25.0, 4903.0)
        assert (trade.volume, trade.cost) == (25.0, -4903.0)


# ── The property the convention exists for ───────────────────────────

class TestPositionFolding:
    def test_sum_of_volumes_is_the_net_position(self) -> None:
        """The reason for signing: SUM(volume) per symbol == units held."""
        fills = [
            _fill(BuySell.BUY, 10.0, 1000.0),
            _fill(BuySell.BUY, 5.0, 500.0),
            _fill(BuySell.SELL, 4.0, 400.0),
        ]
        assert sum(f.volume for f in fills) == 11.0

    def test_sum_of_costs_is_the_net_cash_flow(self) -> None:
        fills = [
            _fill(BuySell.BUY, 10.0, 1000.0),
            _fill(BuySell.SELL, 4.0, 500.0),
        ]
        assert sum(f.cost for f in fills) == -500.0

    def test_fully_closed_position_sums_to_zero(self) -> None:
        fills = [
            _fill(BuySell.BUY, 25.0, 4000.0),
            _fill(BuySell.SELL, 25.0, 4903.0),
        ]
        assert sum(f.volume for f in fills) == 0.0
        # Sold higher than bought → net cash positive (gross of fees).
        assert sum(f.cost for f in fills) == 903.0


class TestAggregationPreservesConvention:
    def _sell_fills(self) -> list[Fill]:
        """Three partial fills of one sell order, broker-native (unsigned)."""
        return [
            Fill(
                execId=f"e{i}", orderId="o1", symbol="MRVL", assetClass="equity",
                side=BuySell.SELL, price=price, volume=vol, cost=price * vol,
                fee=0.5, timestamp=f"2026-07-24T13:55:5{i}", source="flex",
                currency="USD", raw={},
            )
            for i, (price, vol) in enumerate([(196.0, 10.0), (196.2, 10.0), (196.3, 5.0)])
        ]

    def test_aggregated_sell_volume_is_negative(self) -> None:
        trade = aggregate_fills(self._sell_fills())[0]
        assert trade.volume == pytest.approx(-25.0)

    def test_aggregated_sell_cost_is_positive(self) -> None:
        trade = aggregate_fills(self._sell_fills())[0]
        assert trade.cost == pytest.approx(196.0 * 10 + 196.2 * 10 + 196.3 * 5)

    def test_aggregated_fee_stays_positive(self) -> None:
        assert aggregate_fills(self._sell_fills())[0].fee == pytest.approx(1.5)

    def test_vwap_unaffected_by_sign(self) -> None:
        """VWAP weights by abs(volume); on a sell the signs would otherwise
        cancel between numerator and denominator."""
        trade = aggregate_fills(self._sell_fills())[0]
        expected = (196.0 * 10 + 196.2 * 10 + 196.3 * 5) / 25.0
        assert trade.price == pytest.approx(expected)
        assert trade.price > 0
