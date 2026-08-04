"""Funding-carry planner for Gate: size a delta-neutral long-spot / short-perp pair.

A cash-and-carry harvests perpetual funding while staying price-neutral: buy
``N`` units of spot and short the same ``N`` units on the perp. When funding is
positive the short-perp leg is paid every 8h; the two legs' price P&L cancel, so
the return is the collected funding minus fees.

``plan_carry`` turns a target per-leg notional + perp leverage into the concrete
order sizes, capital required, expected annual yield, and the short-perp
liquidation price — all from live marks and the current funding rate. It places
nothing; it is the analysis the operator reviews before executing the two legs
(``sdk.place_order`` for spot + ``perp.place_perp_order`` for the short).
"""

from __future__ import annotations

from typing import Any

from src.trading.connectors.gate import perp
from src.trading.connectors.gate.sdk import GateConfig, get_quote, load_config


def plan_carry(
    coin: str,
    notional_usd: float,
    *,
    leverage: float = 3.0,
    spot_fee: float = 0.001,
    perp_fee: float = 0.0005,
    config: GateConfig | None = None,
) -> dict[str, Any]:
    """Plan a delta-neutral funding carry for ``coin`` at ``notional_usd`` per leg.

    Args:
        coin: Base coin, e.g. ``"BTC"``.
        notional_usd: USD notional of EACH leg (spot long and perp short match).
        leverage: Perp leg leverage. Lower = larger liquidation buffer. 2-3x is
            conservative for a hedged carry.
        spot_fee / perp_fee: Taker fee rates for the round-trip cost estimate.
        config: Gate config (defaults to the saved one; funding/quote are public).

    Returns:
        A plan dict: order sizes, capital required, expected annual carry (USD and
        as a yield on deployed capital), round-trip fee drag, and the short-perp
        liquidation price / buffer.
    """
    cfg = config or load_config()

    fr = perp.get_funding_rate(coin, config=cfg)
    q = get_quote(f"{coin}/USDT", config=cfg)
    price = (q.get("quote") or {}).get("last") or fr.get("mark_price")
    if not price:
        return {"status": "error", "error": f"could not resolve a price for {coin}."}

    ann_funding = (fr.get("annualized_pct") or 0.0) / 100.0
    base_amount = notional_usd / price

    # Capital: full cash for the spot leg + margin for the perp short.
    perp_margin = notional_usd / leverage
    capital = notional_usd + perp_margin

    # Round-trip fees on both legs (enter + exit).
    fee_cost = notional_usd * (spot_fee + perp_fee) * 2

    annual_carry_usd = notional_usd * ann_funding
    net_first_year = annual_carry_usd - fee_cost
    yield_on_capital = annual_carry_usd / capital if capital else 0.0
    net_yield_first_year = net_first_year / capital if capital else 0.0

    # Short-perp liquidation ~ entry * (1 + 1/leverage) (before maintenance/fees).
    # The spot long gains as price rises, offsetting the perp loss — but the perp
    # margin can still be exhausted first if not topped up, so this is the level
    # to watch / rebalance well before.
    liq_price = price * (1 + 1.0 / leverage)
    liq_buffer_pct = (liq_price - price) / price * 100

    return {
        "status": "ok",
        "coin": coin.upper(),
        "price": price,
        "funding_8h_pct": fr.get("funding_8h_pct"),
        "annualized_funding_pct": fr.get("annualized_pct"),
        "legs": {
            "spot_long": {"base_amount": base_amount, "usd": notional_usd, "action": "BUY spot"},
            "perp_short": {"base_amount": base_amount, "usd": notional_usd, "leverage": leverage, "action": "SHORT perp"},
        },
        "capital_required_usd": round(capital, 2),
        "perp_margin_usd": round(perp_margin, 2),
        "expected_annual_carry_usd": round(annual_carry_usd, 2),
        "round_trip_fees_usd": round(fee_cost, 2),
        "net_first_year_usd": round(net_first_year, 2),
        "gross_yield_on_capital_pct": round(yield_on_capital * 100, 2),
        "net_yield_first_year_pct": round(net_yield_first_year * 100, 2),
        "short_liq_price": round(liq_price, 2),
        "liq_buffer_pct": round(liq_buffer_pct, 1),
        "note": (
            "Delta-neutral: spot gain offsets perp loss as price moves. Watch perp "
            "margin; top up or de-lever well before liq. Funding can flip negative "
            "(~15% of the time) — then you pay until it recovers or you unwind."
        ),
    }
