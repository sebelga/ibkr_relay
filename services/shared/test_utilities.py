"""Unit tests for shared.aggregate_fills."""

from typing import Literal

from shared.models import AssetClass, BuySell, Fill, OptionContract
from shared.utilities import aggregate_fills


def _fill(
    exec_id: str,
    order_id: str,
    symbol: str,
    side: BuySell,
    price: float,
    volume: float,
    *,
    asset_class: AssetClass = "option",
    fee: float = 1.0,
    option: OptionContract | None = None,
) -> Fill:
    return Fill(
        execId=exec_id,
        orderId=order_id,
        symbol=symbol,
        assetClass=asset_class,
        side=side,
        price=price,
        volume=volume,
        cost=price * volume,
        fee=fee,
        timestamp="2026-07-17T10:53:56",
        source="commissionReportEvent",
        currency="USD",
        option=option,
        raw={},
    )


def _opt(root: str, strike: float, kind: Literal["call", "put"]) -> OptionContract:
    return OptionContract(
        rootSymbol=root, strike=strike, expiryDate="2028-12-15", type=kind,
    )


def test_partial_fills_same_order_and_symbol_merge_to_one_trade() -> None:
    """Two fills of one instrument on one order aggregate (VWAP) to one trade."""
    fills = [
        _fill("e1", "999", "AAPL", BuySell.BUY, 100.0, 10, asset_class="equity"),
        _fill("e2", "999", "AAPL", BuySell.BUY, 110.0, 30, asset_class="equity"),
    ]
    trades = aggregate_fills(fills)
    assert len(trades) == 1
    t = trades[0]
    assert t.symbol == "AAPL"
    assert t.volume == 40
    assert t.fillCount == 2
    # VWAP: (100*10 + 110*30) / 40 = 107.5
    assert t.price == 107.5


def test_combo_legs_sharing_order_id_split_by_symbol() -> None:
    """A multi-leg combo — both legs share the parent permId (orderId) but are
    distinct option contracts — must produce TWO trades, one per leg, not a
    single merged trade. Mirrors the real SPCX combo (put + call)."""
    order_id = "565614901"
    fills = [
        _fill(
            "0001d588.6a5a3d5a.02.01.01", order_id, "SPCX281215P00130000",
            BuySell.SELL, 47.82, 1, option=_opt("SPCX", 130.0, "put"),
        ),
        _fill(
            "0001d588.6a5a3d5a.03.01.01", order_id, "SPCX281215C00100000",
            BuySell.BUY, 62.63, 1, option=_opt("SPCX", 100.0, "call"),
        ),
    ]
    trades = aggregate_fills(fills)

    assert len(trades) == 2
    by_symbol = {t.symbol: t for t in trades}
    assert set(by_symbol) == {"SPCX281215P00130000", "SPCX281215C00100000"}

    put = by_symbol["SPCX281215P00130000"]
    assert put.side is BuySell.SELL
    assert put.volume == 1
    assert put.fillCount == 1
    assert put.option is not None and put.option.type == "put"

    call = by_symbol["SPCX281215C00100000"]
    assert call.side is BuySell.BUY
    assert call.volume == 1
    assert call.fillCount == 1
    assert call.option is not None and call.option.type == "call"


def test_fills_without_order_id_are_skipped() -> None:
    fills = [_fill("e1", "", "AAPL", BuySell.BUY, 100.0, 1, asset_class="equity")]
    assert aggregate_fills(fills) == []
