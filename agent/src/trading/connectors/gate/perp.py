"""Gate USDT-margined perpetuals (swap) layer for the funding-carry strategy.

Reuses :class:`GateConfig` and the host-separation guard from ``sdk.py`` but
builds a ccxt ``gate`` client in *swap* mode (``defaultType='swap'``) so it can
read funding rates / perp positions and place perp orders. This is the second
leg of a market-neutral funding carry: long spot (``sdk.py``) + short perp
(here) collects funding while staying delta-neutral.

Perp order sizing is in CONTRACTS, not base units. Gate BTC_USDT perp is
``0.0001 BTC`` per contract, ETH ``0.01`` etc. ``place_perp_order`` accepts a
base-asset amount and converts to the nearest whole number of contracts using
the market's ``contractSize`` so the perp leg matches the spot leg's notional.
"""

from __future__ import annotations

from typing import Any

from src.trading.connectors.gate.sdk import (
    GateConfig,
    GateConfigError,
    _assert_host,
    _obj_get,
    _require_ccxt,
    _to_float,
    load_config,
    normalize_symbol,
)


def perp_symbol(symbol: str) -> str:
    """Return the ccxt unified USDT-perp symbol, e.g. ``BTC`` → ``BTC/USDT:USDT``.

    Accepts a coin (``BTC``), a spot pair (``BTC/USDT``, ``BTC-USDT``) or an
    already-formed perp symbol (passed through).
    """
    s = (symbol or "").strip().upper()
    if ":" in s:
        return s
    spot = normalize_symbol(s)
    if "/" not in spot:
        # bare coin → assume USDT quote
        return f"{spot}/USDT:USDT"
    return f"{spot}:{spot.split('/')[1]}"


def _perp_exchange(cfg: GateConfig):
    """Build a ccxt ``gate`` client in swap (USDT-perp) mode for this profile."""
    ccxt = _require_ccxt()
    ex = ccxt.gate(
        {
            "apiKey": cfg.api_key,
            "secret": cfg.api_secret,
            "enableRateLimit": True,
            "timeout": int(cfg.timeout * 1000),
            "options": {"defaultType": "swap"},
        }
    )
    ex.set_sandbox_mode(cfg.is_testnet)
    return ex


def get_funding_rate(symbol: str, *, config: GateConfig | None = None) -> dict[str, Any]:
    """Fetch the current funding rate for one perp (public; no keys needed)."""
    cfg = config or load_config()
    _assert_host(cfg)
    ex = _perp_exchange(cfg)
    sym = perp_symbol(symbol)
    fr = ex.fetch_funding_rate(sym)
    rate = _to_float(_obj_get(fr, "fundingRate"))
    ann = rate * 3 * 365 * 100 if rate is not None else None
    return {
        "status": "ok",
        "symbol": sym,
        "funding_rate": rate,
        "funding_8h_pct": rate * 100 if rate is not None else None,
        "annualized_pct": ann,
        "mark_price": _to_float(_obj_get(fr, "markPrice")),
        "next_funding_time": str(_obj_get(fr, "fundingTimestamp", "") or ""),
    }


def scan_funding(coins: list[str], *, config: GateConfig | None = None) -> dict[str, Any]:
    """Rank a list of coins by their current perp funding rate (carry yield).

    Positive funding means the SHORT-perp side is paid — that is the leg a
    long-spot/short-perp carry holds, so higher = richer carry. Returns rows
    sorted by annualized funding, descending.
    """
    cfg = config or load_config()
    _assert_host(cfg)
    ex = _perp_exchange(cfg)
    ex.load_markets()
    rows: list[dict[str, Any]] = []
    for coin in coins:
        sym = perp_symbol(coin)
        if sym not in ex.markets:
            continue
        try:
            fr = ex.fetch_funding_rate(sym)
        except Exception as exc:  # noqa: BLE001 - skip unavailable, report the rest
            rows.append({"symbol": sym, "error": str(exc)[:80]})
            continue
        rate = _to_float(_obj_get(fr, "fundingRate"))
        if rate is None:
            continue
        rows.append(
            {
                "symbol": sym,
                "funding_8h_pct": rate * 100,
                "annualized_pct": rate * 3 * 365 * 100,
                "mark_price": _to_float(_obj_get(fr, "markPrice")),
            }
        )
    rows.sort(key=lambda r: r.get("annualized_pct", -1e9), reverse=True)
    return {"status": "ok", "profile": cfg.profile, "is_testnet": cfg.is_testnet, "rows": rows}


def get_perp_positions(*, config: GateConfig | None = None) -> dict[str, Any]:
    """Fetch open perpetual positions for the configured account."""
    cfg = config or load_config()
    _assert_host(cfg)
    ex = _perp_exchange(cfg)
    positions = ex.fetch_positions()
    rows = []
    for p in positions or []:
        contracts = _to_float(_obj_get(p, "contracts"))
        if not contracts:
            continue
        rows.append(
            {
                "symbol": _obj_get(p, "symbol"),
                "side": _obj_get(p, "side"),
                "contracts": contracts,
                "notional": _to_float(_obj_get(p, "notional")),
                "entry_price": _to_float(_obj_get(p, "entryPrice")),
                "mark_price": _to_float(_obj_get(p, "markPrice")),
                "unrealized_pnl": _to_float(_obj_get(p, "unrealizedPnl")),
                "leverage": _to_float(_obj_get(p, "leverage")),
                "liquidation_price": _to_float(_obj_get(p, "liquidationPrice")),
            }
        )
    return {
        "status": "ok",
        "profile": cfg.profile,
        "is_testnet": cfg.is_testnet,
        "paper_guard": "host_separated",
        "positions": rows,
    }


def base_to_contracts(ex, sym: str, base_amount: float) -> float:
    """Convert a base-asset amount to a whole number of perp contracts."""
    market = ex.market(sym)
    size = _to_float(market.get("contractSize")) or 1.0
    return round(base_amount / size)


def place_perp_order(
    config: GateConfig | None = None,
    *,
    symbol: str,
    side: str,
    base_amount: float,
    reduce_only: bool = False,
    leverage: float | None = None,
) -> dict[str, Any]:
    """Place a MARKET perp order sized in base-asset units (converted to contracts).

    For a funding carry the perp leg is a SHORT (``side="sell"``) sized to match
    the spot leg. Set ``reduce_only=True`` to unwind. ``leverage`` (if given) is
    applied to the symbol before submitting. Host separation is asserted first,
    so a testnet key can never reach the live host.
    """
    cfg = config or load_config()

    side_clean = str(side or "").strip().lower()
    if side_clean not in ("buy", "sell"):
        return {"status": "error", "error": "side must be 'buy' or 'sell'."}
    amt = _to_float(base_amount)
    if amt is None or amt <= 0:
        return {"status": "error", "error": "base_amount must be a positive number."}

    try:
        _assert_host(cfg)
    except GateConfigError as exc:
        return {"status": "error", "error": str(exc)}

    sym = perp_symbol(symbol)
    try:
        ex = _perp_exchange(cfg)
        ex.load_markets()
        if leverage is not None:
            try:
                ex.set_leverage(int(leverage), sym)
            except Exception as exc:  # noqa: BLE001 - leverage set is best-effort; report if it blocks
                return {"status": "error", "error": f"set_leverage failed: {exc}"}
        contracts = base_to_contracts(ex, sym, amt)
        if contracts <= 0:
            return {"status": "error", "error": f"base_amount {amt} rounds to 0 contracts for {sym}."}
        params: dict[str, Any] = {}
        if reduce_only:
            params["reduceOnly"] = True
        order = ex.create_order(sym, "market", side_clean, contracts, None, params)
    except Exception as exc:  # noqa: BLE001 - fail closed on any ccxt/auth/network error
        return {"status": "error", "error": str(exc)}

    return {
        "status": "ok",
        "order_id": str(_obj_get(order, "id", "")),
        "symbol": _obj_get(order, "symbol", sym),
        "side": str(_obj_get(order, "side", side_clean)),
        "contracts": _obj_get(order, "amount", contracts),
        "reduce_only": reduce_only,
        "profile": cfg.profile,
        "is_testnet": cfg.is_testnet,
        "paper_guard": "host_separated",
        "order_status": str(_obj_get(order, "status", "")),
    }
