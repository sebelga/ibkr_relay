"""Orders namespace — place, cancel, and query orders."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from ib_async import IB, LimitOrder, MarketOrder, Stock

log = logging.getLogger("ib-client")


@dataclass
class OrderResult:
    status: str
    order_id: int
    action: str
    symbol: str
    quantity: int
    order_type: str
    limit_price: float | None = None


class OrdersNamespace:
    """Order operations against IB Gateway."""

    def __init__(self, ib: IB) -> None:
        self._ib = ib

    async def place(
        self,
        symbol: str,
        quantity: int,
        order_type: str,
        limit_price: float | None = None,
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> OrderResult:
        """Place a stock order and return the result.

        Raises ValueError for invalid input, RuntimeError for IB errors.
        """
        if quantity == 0:
            raise ValueError("quantity cannot be zero")
        if not symbol:
            raise ValueError("symbol is required")

        action = "BUY" if quantity > 0 else "SELL"
        abs_qty = abs(quantity)

        if order_type == "LMT":
            if limit_price is None:
                raise ValueError("limitPrice required for LMT orders")
            order = LimitOrder(action, abs_qty, limit_price)
        elif order_type == "MKT":
            order = MarketOrder(action, abs_qty)
        else:
            raise ValueError(f"Unsupported orderType: {order_type}")

        contract = Stock(symbol, exchange, currency)

        try:
            qualified = await self._ib.qualifyContractsAsync(contract)
            if not qualified:
                raise ValueError(f"Could not qualify contract for {symbol}")
        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Contract qualification failed: {exc}") from exc

        log.info(
            "Placing order: %s %d %s %s%s",
            action, abs_qty, symbol, order_type,
            f" @ {limit_price}" if order_type == "LMT" else "",
        )

        try:
            trade = self._ib.placeOrder(contract, order)
        except Exception as exc:
            raise RuntimeError(f"Order placement failed: {exc}") from exc

        # Give IBKR a moment to acknowledge
        await asyncio.sleep(1)

        return OrderResult(
            status=trade.orderStatus.status,
            order_id=trade.order.orderId,
            action=action,
            symbol=symbol,
            quantity=abs_qty,
            order_type=order_type,
            limit_price=limit_price if order_type == "LMT" else None,
        )
