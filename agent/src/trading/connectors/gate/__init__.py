"""Gate (gate.io, spot) trading connector.

Read + order placement via the ``ccxt`` library's unified ``gate`` exchange
client (REST). A ``broker_sdk`` transport, structurally identical to the Binance
connector.

Paper-vs-live separation is structural: the Gate testnet (paper) and live
mainnet use DIFFERENT API keys and DIFFERENT hosts
(``api-testnet.gateapi.io`` vs ``api.gateio.ws``), selected via
``set_sandbox_mode``. The configured ``profile`` selects the host and is the
authoritative discriminator, recorded on every payload and never flipped
implicitly. Gate spot has no positions — holdings are non-zero balances, so
``get_positions`` shapes the non-zero balances from ``fetch_balance`` as rows.

Note: Gate's public testnet is oriented toward derivatives; spot testnet
coverage can be thin (limited pairs/liquidity). The connector still fails closed
on host mismatch, so a testnet key can never reach the live host.
"""
