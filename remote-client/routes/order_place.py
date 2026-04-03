"""POST /ibkr/order — place a stock order."""

from __future__ import annotations

import json
import logging

from aiohttp import web

from client import IBClient

log = logging.getLogger("routes")


async def handle_order(request: web.Request) -> web.Response:
    client: IBClient = request.app["client"]

    if not client.is_connected:
        return web.json_response(
            {"error": "Not connected to IB Gateway"}, status=503
        )

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    quantity = body.get("quantity")
    symbol = body.get("symbol", "").upper().strip()
    order_type = body.get("orderType", "").upper().strip()
    limit_price = body.get("limitPrice")
    exchange = body.get("exchange", "SMART").upper().strip()
    currency = body.get("currency", "USD").upper().strip()

    if not quantity or not symbol:
        return web.json_response(
            {"error": "quantity and symbol are required"}, status=400
        )

    try:
        quantity = int(quantity)
    except (ValueError, TypeError):
        return web.json_response(
            {"error": "quantity must be an integer"}, status=400
        )

    try:
        if limit_price is not None:
            limit_price = float(limit_price)
    except (ValueError, TypeError):
        return web.json_response(
            {"error": "limitPrice must be a number"}, status=400
        )

    try:
        result = await client.orders.place(
            symbol=symbol,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            exchange=exchange,
            currency=currency,
        )
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except RuntimeError as exc:
        log.error("Order failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    response = {
        "status": result.status,
        "orderId": result.order_id,
        "action": result.action,
        "symbol": result.symbol,
        "quantity": result.quantity,
        "orderType": result.order_type,
    }
    if result.limit_price is not None:
        response["limitPrice"] = result.limit_price

    log.info("Order placed: %s", json.dumps(response))
    return web.json_response(response)
