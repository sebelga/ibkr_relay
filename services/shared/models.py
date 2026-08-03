"""Shared Pydantic models and type aliases (CommonFill contract).

!! PUBLIC CONTRACT — every type defined here is exported to consumers
!! via the generated TypeScript and Python type packages (make types).
!! Do NOT add general internal helpers, mapping dicts, or utility
!! functions here — those belong in utilities.py.
!!
!! Exception: private ``json_schema_extra`` hooks (e.g.
!! :func:`_all_fields_required`) live inline with the models they decorate,
!! since they're single-purpose schema plumbing, not general helpers. This
!! mirrors the ``_require_discriminators`` pattern in notifier/models.py.

Outbound webhook payload contracts live in relay_core/notifier/models.py.
"""

from enum import Enum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

RelayName = Literal["ibkr", "kraken"]
"""Allowed relay identifiers — single source of truth.

Used to validate RELAYS env var, discriminate webhook payloads, and
namespace dedup/metadata DB keys. Add new brokers here.
"""

AssetClass = Literal["equity", "option", "crypto", "future", "forex", "other"]

OrderType = Literal["market", "limit", "stop", "stop_limit", "trailing_stop"]


class BuySell(str, Enum):
    BUY = "buy"
    SELL = "sell"


Source = Literal[
    "flex", "execDetailsEvent", "commissionReportEvent",  # IBKR
    "rest_poll", "ws_execution",                           # Kraken
]


FxRateSource = Literal["historical", "latest"]


def _all_fields_required(schema: dict[str, Any]) -> None:
    """Mark every declared field as required in JSON Schema.

    Pydantic's default JSON serialization always emits keys (``None`` →
    ``null``, never omitted), so optional fields on the wire are always
    present. Without this hook, json-schema-to-typescript generates
    ``field?: T | null`` — implying the key may be missing — which
    doesn't match the actual payload. This hook forces the tighter
    ``field: T | null``.
    """
    properties = schema.get("properties", {})
    schema["required"] = list(properties.keys())


def _apply_sign_convention(
    side: BuySell, volume: float, cost: float, fee: float,
) -> tuple[float, float, float]:
    """Force ``volume`` / ``cost`` / ``fee`` onto the canonical sign convention.

    See the "Sign convention" block on :class:`Fill` for the contract itself.
    Summary: ``volume`` is a **position delta** (buy > 0, sell < 0) and
    ``cost`` is the matching **cash delta**, so it carries the *opposite*
    sign (buy < 0 — money out; sell > 0 — money in). ``fee`` is always a
    debit and therefore always positive.

    Every incoming value is reduced to its magnitude and re-signed from
    ``side``, which makes this idempotent and lets each adapter forward the
    broker's native value untouched. That matters because brokers disagree,
    and not only about *whether* they sign:

    * IBKR Flex signs ``quantity`` our way (buy +, sell -) but reports
      ``cost`` as a **cost-basis** delta — buy +, sell - — i.e. inverted
      relative to a cash delta.
    * The IBKR bridge (``ib_async``), Kraken REST, and Kraken WS all report
      unsigned magnitudes with direction carried only in the side field.

    Normalising here rather than in each adapter means a new relay cannot
    silently introduce a fourth convention: whatever it forwards, the
    contract holds. ``side`` is validated by the adapters before this runs
    (never defaulted — see the financial-enum rule in CLAUDE.md), so it is
    trusted as the source of truth for direction.

    Lives beside the models rather than in ``utilities.py`` because
    ``utilities.py`` imports from this module — the reverse import would be
    circular — and because it is single-purpose model plumbing, not a
    general helper (same carve-out as :func:`_all_fields_required`).
    """
    magnitude_volume, magnitude_cost = abs(volume), abs(cost)
    if side is BuySell.BUY:
        signed_volume, signed_cost = magnitude_volume, -magnitude_cost
    else:
        signed_volume, signed_cost = -magnitude_volume, magnitude_cost
    # ``-abs(0.0)`` is ``-0.0``, which survives JSON round-trips as "-0.0"
    # and reads as a bug downstream. ``or 0.0`` maps both zeros to +0.0.
    return signed_volume or 0.0, signed_cost or 0.0, abs(fee) or 0.0


class OptionContract(BaseModel):
    """Option-specific contract metadata.

    Populated only on fills/trades whose ``assetClass == "option"``. Future
    derivatives (futures, FOPs, warrants) will get their own sibling
    contract objects rather than reusing this one — see
    ``docs/migrate-trade-models-to-discriminated-union.md`` for the planned
    discriminated-union evolution.
    """

    model_config = ConfigDict(
        extra="forbid", json_schema_extra=_all_fields_required,
    )

    # Underlying ticker (e.g. "AVGO" for an AVGO option).
    rootSymbol: str
    strike: float
    # Last trading day in canonical ISO ``YYYY-MM-DD`` form (e.g. "2026-05-08").
    expiryDate: str
    type: Literal["call", "put"]


class Fill(BaseModel):
    """Individual execution from a broker (CommonFill spec).

    **Sign convention (PUBLIC CONTRACT).** RelayPort deliberately departs
    from the FIX/exchange norm of "unsigned magnitude + side flag". Here
    ``volume`` and ``cost`` are *signed deltas*, so consumers can fold a
    stream of trades into a position with a plain ``SUM``:

    ===========  ===========================  ========  ========
    Field        Meaning                      Buy       Sell
    ===========  ===========================  ========  ========
    ``volume``   position delta (units)       positive  negative
    ``cost``     cash delta (currency)        negative  positive
    ``fee``      amount paid (always a debit) positive  positive
    ``price``    unit price (never signed)    positive  positive
    ===========  ===========================  ========  ========

    So ``SUM(volume)`` grouped by ``symbol`` yields the net position, and
    ``SUM(cost) - SUM(fee)`` yields the net cash impact.

    Two caveats consumers must know. (1) ``SUM(volume)`` is *net units
    transacted through RelayPort*, not a custody-accurate holding — splits,
    transfers, and option assignment/exercise move a real position without
    ever producing a fill. (2) Never sum across asset classes: an option's
    ``volume`` is in contracts, and one contract covers ``multiplier``
    (typically 100) shares. Group by ``symbol`` — OCC tickers keep option
    series distinct from their underlying.

    ``side`` remains authoritative for direction and is always consistent
    with the sign; it is not redundant, since a zero-volume fill carries no
    sign. Signs are enforced by :func:`_apply_sign_convention`, never by
    the adapters, so a broker's native convention cannot leak out.
    """

    model_config = ConfigDict(
        extra="forbid", json_schema_extra=_all_fields_required,
    )

    execId: str
    orderId: str
    symbol: str
    assetClass: AssetClass
    side: BuySell
    orderType: OrderType | None = None
    # Unit price — always a positive magnitude, never signed. Direction
    # lives on volume/cost; signing price too would double-count it and
    # break the VWAP weighting in aggregate_fills.
    price: float
    # Position delta: positive on buy, negative on sell.
    volume: float
    # Cash delta: negative on buy (money out), positive on sell (money in).
    cost: float
    # Always positive — a fee is a debit regardless of direction.
    fee: float
    timestamp: str
    source: Source
    # ISO-4217 code of the asset traded (e.g. "USD" for AAPL). None when the
    # broker does not expose an unambiguous fiat currency for the fill (e.g.
    # crypto-quoted-in-crypto pairs like ETH/BTC).
    currency: str | None = None
    # Option-contract metadata. Populated when ``assetClass == "option"``,
    # None for every other asset class. Cross-field consistency (option
    # populated iff assetClass == "option") is enforced by the producing
    # parsers, not by the model itself — see migration plan in docs/.
    option: OptionContract | None = None
    raw: dict[str, Any]

    @model_validator(mode="after")
    def _enforce_sign_convention(self) -> Self:
        self.volume, self.cost, self.fee = _apply_sign_convention(
            self.side, self.volume, self.cost, self.fee,
        )
        return self


class Trade(BaseModel):
    """Aggregated trade (one or more fills for the same order).

    Carries the same signed-delta convention as :class:`Fill` — see the
    "Sign convention" table there. ``volume`` / ``cost`` / ``fee`` are the
    sums of the constituent fills, so the convention survives aggregation
    unchanged and a stream of Trades folds into a position by ``SUM``.
    """

    model_config = ConfigDict(
        extra="forbid", json_schema_extra=_all_fields_required,
    )

    orderId: str
    symbol: str
    assetClass: AssetClass
    side: BuySell
    orderType: OrderType | None = None
    # Quantity-weighted average price — a positive magnitude (see Fill.price).
    price: float
    # Summed position delta: positive on buy, negative on sell.
    volume: float
    # Summed cash delta: negative on buy, positive on sell.
    cost: float
    # Summed fees — always positive.
    fee: float
    fillCount: int
    execIds: list[str]
    timestamp: str
    source: Source
    # Copied from the last fill — ISO-4217 or None (see Fill.currency).
    currency: str | None = None
    # Copied from the last fill — option contract metadata for option
    # trades, None for every other asset class (see Fill.option).
    option: OptionContract | None = None
    # Units of fxRateBase per 1 unit of currency, such that
    # cost * fxRate == cost_in_base_currency. Populated by the FX
    # enrichment layer when FX_RATES_ENABLED=true and currency is known.
    fxRate: float | None = None
    fxRateBase: str | None = None
    fxRateSource: FxRateSource | None = None
    raw: dict[str, Any]

    @model_validator(mode="after")
    def _enforce_sign_convention(self) -> Self:
        self.volume, self.cost, self.fee = _apply_sign_convention(
            self.side, self.volume, self.cost, self.fee,
        )
        return self
