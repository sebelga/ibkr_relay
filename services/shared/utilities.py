"""Internal utilities for aggregating fills.

These are internal to the relay — not exported to consumer packages.
"""

from .models import Fill, Trade


def aggregate_fills(fills: list[Fill]) -> list[Trade]:
    """Group fills by ``(orderId, symbol)`` and compute aggregated Trades.

    * ``volume`` — sum of all fills.
    * ``price`` — quantity-weighted average (VWAP).
    * Financial fields (cost, fee) — summed.
    * ``timestamp`` — latest fill's value (lexicographic max).
    * ``execIds`` — execId per fill.
    * ``fillCount`` — number of fills in the group.
    * ``raw`` — first fill's raw dict.

    The grouping key includes ``symbol`` — not just ``orderId`` — because a
    single order can produce fills on distinct instruments that must NOT be
    merged into one trade. IBKR multi-leg (combo/BAG) orders are the concrete
    case: every leg shares the parent order's ``permId`` (which the bridge
    maps to ``Fill.orderId``), so grouping on ``orderId`` alone would collapse
    a call leg and a put leg into a single nonsensical trade. For ordinary
    single-instrument orders every fill shares one symbol, so the key reduces
    to ``orderId`` and behaviour is unchanged.

    Aggregation is the only responsibility of this function — order of the
    returned list is not part of its contract. The chronological-order
    guarantee for notifier dispatch is enforced at each ``notify()`` call
    site (poller and listener engines), so callers that aggregate-then-
    concatenate-then-notify still get a sorted payload.
    """
    groups: dict[tuple[str, str], list[Fill]] = {}
    for fill in fills:
        if not fill.orderId:
            continue
        groups.setdefault((fill.orderId, fill.symbol), []).append(fill)

    trades: list[Trade] = []
    for order_fills in groups.values():
        # Weighted average price
        abs_total = sum(abs(f.volume) for f in order_fills)
        avg_price = (
            sum(abs(f.volume) * f.price for f in order_fills) / abs_total
            if abs_total else 0.0
        )

        total_volume = sum(f.volume for f in order_fills)
        total_cost = sum(f.cost for f in order_fills)
        total_fee = sum(f.fee for f in order_fills)

        last = max(order_fills, key=lambda f: f.timestamp)

        trades.append(Trade(
            orderId=last.orderId,
            symbol=last.symbol,
            assetClass=last.assetClass,
            side=last.side,
            orderType=last.orderType,
            price=round(avg_price, 8),
            volume=total_volume,
            cost=round(total_cost, 4),
            fee=round(total_fee, 4),
            fillCount=len(order_fills),
            execIds=[f.execId for f in order_fills],
            timestamp=last.timestamp,
            source=last.source,
            currency=last.currency,
            option=last.option,
            raw=order_fills[0].raw,
        ))

    return trades
