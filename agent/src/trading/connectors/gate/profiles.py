"""Built-in Gate (gate.io, spot) connector profiles.

Read-only paper (testnet) and live profiles plus order-placing paper and live
profiles. Paper and live use different key pairs and different hosts, so they
are distinct profiles. The order-placing live profile carries an
``orders.place.requires_mandate`` capability — the higher trading layer must
gate it behind the user's mandate before any order reaches the connector.
"""

from __future__ import annotations

from src.trading.types import READ_CAPABILITIES, TradingProfile

GATE_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="gate-paper-sdk",
        connector="gate",
        label="Gate Spot Testnet · ccxt",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "paper"},
        notes=(
            "Reads a Gate spot testnet account (api-testnet.gateapi.io) via ccxt. "
            "Testnet keys cannot reach the live host."
        ),
    ),
    TradingProfile(
        id="gate-live-sdk-readonly",
        connector="gate",
        label="Gate Spot Live · ccxt Read-Only",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "live-readonly"},
        notes="Reads a Gate spot live account only (api.gateio.ws). Order placement is not exposed in this profile.",
    ),
    TradingProfile(
        id="gate-paper-trade",
        connector="gate",
        label="Gate Spot Testnet · ccxt Trading",
        environment="paper",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES + ("orders.place",),
        readonly=False,
        config={"profile": "paper"},
        notes=(
            "Places and cancels orders on a Gate spot testnet account "
            "(api-testnet.gateapi.io) via ccxt. Testnet keys cannot reach the live "
            "host, so no order from this profile can touch real funds."
        ),
    ),
    TradingProfile(
        id="gate-live-trade",
        connector="gate",
        label="Gate Spot Live · ccxt Trading",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES + ("orders.place.requires_mandate",),
        readonly=False,
        config={"profile": "live"},
        notes=(
            "Places orders on a Gate spot live account (api.gateio.ws) via ccxt. "
            "Live order placement is gated behind a user-defined mandate and kill "
            "switch."
        ),
    ),
)
