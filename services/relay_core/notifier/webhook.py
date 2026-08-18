"""Webhook notifier — HMAC-SHA256 signed POST to a target URL."""

import hashlib
import hmac
import logging
import os

import httpx
from pydantic import BaseModel

from relay_core.env import get_env
from shared import safe_http_error_context

from .base import BaseNotifier

log = logging.getLogger("notifier.webhook")

_DEBUG_SERVICE_NAME = "debug"
_DEBUG_SERVICE_PORT = 9000

# Generous read budget: receivers that only ack after processing (or that
# sit on a cold-started serverless runtime) can take well over 10s to
# respond even though they accepted the request. A premature read timeout
# is counted as a delivery failure and triggers a duplicate re-send.
_TIMEOUT = httpx.Timeout(10.0, read=30.0)


# ---------------------------------------------------------------------------
# Env var getters — single source of truth, .strip() applied once
# ---------------------------------------------------------------------------

def get_debug_webhook_path() -> str:
    return os.environ.get("DEBUG_WEBHOOK_PATH", "").strip()


def _get_target_webhook_url(prefix: str, suffix: str) -> str:
    return get_env("TARGET_WEBHOOK_URL", prefix, suffix)


def _get_webhook_secret(prefix: str, suffix: str) -> str:
    return get_env("WEBHOOK_SECRET", prefix, suffix)


def _get_webhook_header_name(prefix: str, suffix: str) -> str:
    return get_env("WEBHOOK_HEADER_NAME", prefix, suffix)


def _get_webhook_header_value(prefix: str, suffix: str) -> str:
    return get_env("WEBHOOK_HEADER_VALUE", prefix, suffix)


def _resolve_webhook_url(prefix: str, suffix: str) -> str:
    """Return the webhook target URL, preferring debug inbox when configured.

    Checks DEBUG_WEBHOOK_PATH first. If set, constructs the container-to-container
    URL for the debug service. Otherwise falls back to TARGET_WEBHOOK_URL{suffix}.
    Result is computed once per WebhookNotifier instance (cached in self._url).
    """
    debug_path = get_debug_webhook_path()
    if debug_path:
        log.info("DEBUG_WEBHOOK_PATH set — using debug inbox")
        return (
            f"http://{_DEBUG_SERVICE_NAME}:{_DEBUG_SERVICE_PORT}/debug/webhook/"
            f"{debug_path}"
        )
    return _get_target_webhook_url(prefix, suffix)


class WebhookNotifier(BaseNotifier):
    """Send JSON payloads to a webhook URL with HMAC-SHA256 signature."""

    name = "webhook"

    def __init__(self, prefix: str = "", suffix: str = "") -> None:
        self._prefix = prefix
        self._suffix = suffix
        self._url = _resolve_webhook_url(prefix, suffix)
        self._secret = _get_webhook_secret(prefix, suffix)
        self._header_name = _get_webhook_header_name(prefix, suffix)
        self._header_value = _get_webhook_header_value(prefix, suffix)

        # Validate using already-resolved values — no env re-reads.
        # URL is not required when DEBUG_WEBHOOK_PATH is set because
        # _resolve_webhook_url already resolved to the debug inbox.
        # Show the prefixed var name when a prefix is active.
        missing: list[str] = []
        if not self._url:
            missing.append(f"{prefix}TARGET_WEBHOOK_URL{suffix}" if prefix
                           else f"TARGET_WEBHOOK_URL{suffix}")
        if not self._secret:
            missing.append(f"{prefix}WEBHOOK_SECRET{suffix}" if prefix
                           else f"WEBHOOK_SECRET{suffix}")
        if missing:
            msg = f"Notifier {self.name!r} requires env vars: {', '.join(missing)}"
            log.error("%s", msg)
            raise SystemExit(msg)

    @staticmethod
    def required_env_vars() -> list[str]:
        return ["TARGET_WEBHOOK_URL", "WEBHOOK_SECRET"]

    @staticmethod
    def _dry_run_summary(payload: BaseModel) -> str:
        payload_data = payload.model_dump()
        data = payload_data.get("data")
        if isinstance(data, list):
            symbols = sorted(
                {
                    trade["symbol"]
                    for trade in data
                    if isinstance(trade, dict) and isinstance(trade.get("symbol"), str)
                }
            )
            return (
                f"{payload.__class__.__name__}(trade_count={len(data)}, "
                f"symbols={symbols})"
            )
        return payload.__class__.__name__

    def send(self, payload: BaseModel) -> None:
        body = payload.model_dump_json(indent=2)

        if not self._url:
            log.info("Webhook dry-run: %s", self._dry_run_summary(payload))
            log.debug(
                "Webhook payload (dry-run, redacted):\n%s",
                payload.model_dump_json(
                    indent=2,
                    exclude={"accountId", "acctAlias"},
                ),
            )
            return

        signature = hmac.new(
            self._secret.encode(), body.encode(), hashlib.sha256
        ).hexdigest()

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Signature-256": f"sha256={signature}",
        }
        # Content-derived, stable across retries and re-sends of the same
        # trades — receivers deduplicate on it (delivery is at-least-once).
        delivery_id = getattr(payload, "deliveryId", None)
        if isinstance(delivery_id, str) and delivery_id:
            headers["X-Delivery-Id"] = delivery_id
        if self._header_name:
            headers[self._header_name] = self._header_value

        resp = httpx.post(
            self._url,
            content=body,
            headers=headers,
            timeout=_TIMEOUT,
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Surface a sanitised diagnostic context (request-id, capped
            # text/json body) so downstream logs and alert emails can
            # show *why* the receiver rejected the request without
            # echoing arbitrary HTML/binary content.
            context = safe_http_error_context(exc.response)
            msg = f"{exc} — {context}" if context else str(exc)
            raise httpx.HTTPStatusError(
                msg,
                request=exc.request,
                response=exc.response,
            ) from exc
        log.info("Webhook sent — status %d", resp.status_code)
