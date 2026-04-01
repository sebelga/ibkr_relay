"""IBKR Webhook Relay — listens for order fills and POSTs to a webhook."""

import hashlib
import hmac
import json
import logging
import os
import time

import httpx
from ib_async import IB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("relay")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
IB_HOST = os.environ.get("IB_HOST", "ib-gateway")
TRADING_MODE = os.environ.get("TRADING_MODE", "paper")
IB_PORT = int(os.environ.get("IB_LIVE_PORT" if TRADING_MODE == "live" else "IB_PAPER_PORT", "4004"))
TARGET_WEBHOOK_URL = os.environ["TARGET_WEBHOOK_URL"]
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
CLIENT_ID = 1

INITIAL_RETRY_DELAY = 10
MAX_RETRY_DELAY = 300
retry_delay = INITIAL_RETRY_DELAY


# ---------------------------------------------------------------------------
# Webhook delivery
# ---------------------------------------------------------------------------
def send_webhook(payload: dict) -> None:
    body = json.dumps(payload, default=str)
    signature = hmac.new(
        WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256
    ).hexdigest()

    try:
        resp = httpx.post(
            TARGET_WEBHOOK_URL,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature-256": f"sha256={signature}",
            },
            timeout=10.0,
        )
        log.info("Webhook sent — status %d", resp.status_code)
    except httpx.HTTPError as exc:
        log.error("Webhook delivery failed: %s", exc)


# ---------------------------------------------------------------------------
# IB event handlers
# ---------------------------------------------------------------------------
def on_fill(trade, fill):
    payload = {
        "event": "fill",
        "symbol": trade.contract.symbol,
        "secType": trade.contract.secType,
        "exchange": trade.contract.exchange,
        "action": fill.execution.side,
        "quantity": float(fill.execution.shares),
        "price": float(fill.execution.price),
        "time": fill.execution.time.isoformat(),
        "orderId": trade.order.orderId,
        "execId": fill.execution.execId,
        "account": fill.execution.acctNumber,
    }
    log.info(
        "Fill: %s %s %s @ %s",
        payload["action"],
        payload["quantity"],
        payload["symbol"],
        payload["price"],
    )
    send_webhook(payload)


def on_order_status(trade):
    log.info(
        "Order status: %s %s %s — %s (filled %s/%s)",
        trade.order.action,
        trade.order.totalQuantity,
        trade.contract.symbol,
        trade.orderStatus.status,
        trade.orderStatus.filled,
        trade.order.totalQuantity,
    )


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------
ib = IB()


def connect():
    global retry_delay
    while True:
        try:
            log.info("Connecting to IB Gateway at %s:%d ...", IB_HOST, IB_PORT)
            ib.connect(IB_HOST, IB_PORT, clientId=CLIENT_ID, timeout=20)
            log.info("Connected — accounts: %s", ib.managedAccounts())
            retry_delay = INITIAL_RETRY_DELAY
            return
        except Exception as exc:
            log.warning(
                "Connection failed: %s — retrying in %ds", exc, retry_delay
            )
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)


def on_disconnect():
    log.warning("Disconnected from IB Gateway — will reconnect")
    time.sleep(retry_delay)
    connect()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info("IBKR Webhook Relay starting (mode=%s)", TRADING_MODE)

    connect()

    ib.execDetailsEvent += on_fill
    ib.orderStatusEvent += on_order_status
    ib.disconnectedEvent += on_disconnect

    log.info("Listening for order events ...")
    ib.run()


if __name__ == "__main__":
    main()
