#!/usr/bin/env bash
# Place an order via the IBKR relay HTTPS API.
#
# Usage:
#   ./order.sh  2 TSLA MKT          # buy 2 shares market
#   ./order.sh -2 TSLA MKT          # sell 2 shares market
#   ./order.sh  2 TSLA LMT 352.5    # buy 2 shares limit $352.5
#   ./order.sh -2 TSLA LMT 380      # sell 2 shares limit $380

set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <quantity> <symbol> <MKT|LMT> [limitPrice]"
  echo "  Positive quantity = BUY, negative = SELL"
  exit 1
fi

QTY="$1"
SYMBOL="$2"
ORDER_TYPE="$(echo "$3" | tr '[:lower:]' '[:upper:]')"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load API_TOKEN and VNC_DOMAIN from .env
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  API_TOKEN=$(grep -E '^API_TOKEN=' "$SCRIPT_DIR/.env" | cut -d= -f2-)
  TRADE_DOMAIN=$(grep -E '^TRADE_DOMAIN=' "$SCRIPT_DIR/.env" | cut -d= -f2-)
fi

if [[ -z "${API_TOKEN:-}" ]]; then
  echo "Error: API_TOKEN not found in .env"
  exit 1
fi

if [[ -z "${TRADE_DOMAIN:-}" ]]; then
  echo "Error: TRADE_DOMAIN not found in .env"
  exit 1
fi

# Build JSON payload
if [[ "$ORDER_TYPE" == "LMT" ]]; then
  if [[ $# -lt 4 ]]; then
    echo "Error: limitPrice required for LMT orders"
    exit 1
  fi
  LIMIT_PRICE="$4"
  JSON=$(printf '{"quantity":%s,"symbol":"%s","orderType":"LMT","limitPrice":%s}' "$QTY" "$SYMBOL" "$LIMIT_PRICE")
elif [[ "$ORDER_TYPE" == "MKT" ]]; then
  JSON=$(printf '{"quantity":%s,"symbol":"%s","orderType":"MKT"}' "$QTY" "$SYMBOL")
else
  echo "Error: orderType must be MKT or LMT (got: $ORDER_TYPE)"
  exit 1
fi

ACTION="BUY"
[[ "$QTY" -lt 0 ]] && ACTION="SELL"
ABS_QTY="${QTY#-}"

echo "Placing order: $ACTION $ABS_QTY $SYMBOL $ORDER_TYPE${LIMIT_PRICE:+ @ \$$LIMIT_PRICE}"

curl -s -X POST "https://${TRADE_DOMAIN}/ibkr/order" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -d "$JSON" | python3 -m json.tool 2>/dev/null || echo "Request failed"
