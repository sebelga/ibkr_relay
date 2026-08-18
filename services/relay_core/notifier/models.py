"""Outbound payload contracts for notifier backends.

!! PUBLIC CONTRACT — every type defined here is exported to consumers
!! via the generated TypeScript and Python type packages (make types).
!! Add new payload variants here as new notifier event types are introduced.
"""

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from shared import RelayName, Trade


def _require_defaulted_fields(schema: dict[str, Any]) -> None:
    """Keep always-populated fields required in JSON Schema despite defaults.

    ``type`` and ``deliveryId`` carry Python-side defaults (literal value /
    validator-computed) but are always present on the wire — consumers must
    be able to rely on them.
    """
    req: list[str] = schema.get("required", [])
    for f in ("relay", "type", "deliveryId"):
        if f not in req:
            req.append(f)
    schema["required"] = req


def compute_delivery_id(
    relay: str, trades: list[Trade], errors: list[str],
) -> str:
    """Deterministic, content-derived identifier for a webhook delivery.

    Same trade content → same ID, across retry attempts AND across
    engine re-sends after a failed cycle (e.g. a read-timeout on a slow
    receiver followed by the next poll cycle re-sending the same fills).
    Receivers deduplicate on it directly; delivery is at-least-once.

    Derived from broker-assigned identities (``orderId`` + ``execIds``),
    never from trade values (price/volume/timestamp) — value tuples can
    legitimately collide across distinct trades, and a collision here
    would make the receiver silently drop a real trade. Error-only
    payloads (no trades) hash the error strings instead so they don't
    all share one ID per relay.
    """
    if trades:
        parts = sorted(
            f"{t.orderId}:{','.join(sorted(t.execIds))}" for t in trades
        )
    else:
        parts = sorted(errors)
    material = f"{relay}|{'|'.join(parts)}"
    return hashlib.sha256(material.encode()).hexdigest()[:16]


class WebhookPayloadTrades(BaseModel):
    """Webhook payload for trade execution events."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra=_require_defaulted_fields,
    )

    relay: RelayName
    type: Literal["trades"] = "trades"
    deliveryId: str = ""
    data: list[Trade]
    errors: list[str]

    @model_validator(mode="after")
    def _ensure_delivery_id(self) -> "WebhookPayloadTrades":
        """Auto-compute ``deliveryId`` so no construction site can omit it.

        An explicitly provided (non-empty) value is preserved — round-trip
        validation of a received payload must not alter it.
        """
        if not self.deliveryId:
            self.deliveryId = compute_delivery_id(
                self.relay, self.data, self.errors,
            )
        return self


# Discriminated-union alias — grows as new event types are added.
WebhookPayload = WebhookPayloadTrades
