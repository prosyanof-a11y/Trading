#!/usr/bin/env python
"""Gate funding-carry helper CLI (read-only planning; no orders placed).

Usage:
    python scripts/gate_carry.py scan [COIN ...]
    python scripts/gate_carry.py plan COIN NOTIONAL_USD [LEVERAGE]

Examples:
    python scripts/gate_carry.py scan
    python scripts/gate_carry.py scan BTC ETH SOL TON
    python scripts/gate_carry.py plan BTC 1000 3

`scan` ranks coins by current perp funding (annualized carry). `plan` sizes a
delta-neutral long-spot / short-perp pair and shows capital, expected yield, and
the short liquidation buffer. Uses LIVE public Gate data — no API keys required
for these read-only calls. Execution of the two legs is a separate, mandate-
gated step and is NOT performed here.
"""

from __future__ import annotations

import sys

from src.trading.connectors.gate import funding_carry as fc
from src.trading.connectors.gate import perp
from src.trading.connectors.gate.sdk import GateConfig

DEFAULT_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "LTC", "LINK", "AVAX", "TON"]

# Read-only public data lives on the live host; keys are not needed for scan/plan.
CFG = GateConfig(profile="live-readonly")


def cmd_scan(coins: list[str]) -> int:
    r = perp.scan_funding(coins or DEFAULT_COINS, config=CFG)
    print(f"Gate perp funding — {'testnet' if r['is_testnet'] else 'live'}")
    print(f"{'symbol':<16}{'8h %':>10}{'annualized %':>15}")
    for row in r["rows"]:
        if "error" in row:
            print(f"{row['symbol']:<16}  {row['error']}")
            continue
        print(f"{row['symbol']:<16}{row['funding_8h_pct']:>10.4f}{row['annualized_pct']:>15.1f}")
    print("\nPositive funding = the short-perp (carry) leg is paid. Higher = richer carry.")
    return 0


def cmd_plan(coin: str, notional: float, leverage: float) -> int:
    p = fc.plan_carry(coin, notional, leverage=leverage, config=CFG)
    if p["status"] != "ok":
        print(f"error: {p.get('error')}")
        return 1
    sl = p["legs"]["spot_long"]
    ps = p["legs"]["perp_short"]
    print(f"=== {p['coin']} funding carry | {notional:g} USD/leg | {leverage:g}x ===")
    print(f"  price               {p['price']}")
    print(f"  funding (annualized) {p['annualized_funding_pct']:.1f}%")
    print(f"  LEG 1  BUY  spot     {sl['base_amount']:.6f} {p['coin']}  (~{sl['usd']:g} USD)")
    print(f"  LEG 2  SHORT perp    {ps['base_amount']:.6f} {p['coin']}  ({leverage:g}x)")
    print(f"  capital required     {p['capital_required_usd']} USD  (perp margin {p['perp_margin_usd']})")
    print(f"  expected annual carry {p['expected_annual_carry_usd']} USD")
    print(f"  net first year        {p['net_first_year_usd']} USD (after round-trip fees {p['round_trip_fees_usd']})")
    print(f"  yield on capital      gross {p['gross_yield_on_capital_pct']}%  |  net {p['net_yield_first_year_pct']}%")
    print(f"  short liquidation @   {p['short_liq_price']}  (buffer +{p['liq_buffer_pct']}%)")
    print(f"\n  {p['note']}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1].lower()
    if cmd == "scan":
        return cmd_scan([c.upper() for c in argv[2:]])
    if cmd == "plan":
        if len(argv) < 4:
            print("usage: plan COIN NOTIONAL_USD [LEVERAGE]")
            return 2
        coin = argv[2].upper()
        notional = float(argv[3])
        leverage = float(argv[4]) if len(argv) > 4 else 3.0
        return cmd_plan(coin, notional, leverage)
    print(f"unknown command: {cmd}")
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
