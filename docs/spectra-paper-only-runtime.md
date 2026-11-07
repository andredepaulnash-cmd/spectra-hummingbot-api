# Spectra paper-only API runtime

## Purpose

`SPECTRA_PAPER_ONLY=true` places this Hummingbot API process into a fail-closed, non-executing support mode. It is a containment setting for the Spectra local paper environment; it is not itself a paper exchange, market-data simulator, or Core authorization receipt.

## What the mode does

- Allows only a reviewed set of paper order, executor, account-read, portfolio, and market-data POST routes. Gateway, wallet, credential-management, bot orchestration, script, Docker, and every unreviewed mutation route remain blocked.
- Uses exact route patterns. A new POST endpoint is blocked by default until reviewed.
- Initializes only connector names ending in `_paper_trade`; the connector service independently rejects live CEX, perpetual, and Gateway connector names, including lazy connector creation.
- Starts the Hummingbot executor control loop and account service only against those paper connectors, so simulated orders can be created and managed without starting live connectors.
- Does not start bot/MQTT orchestration, Gateway monitoring, Docker actions, or market-data background feeds. Paper connectors own their public market feed.
- Does not run orphaned-executor cleanup in paper mode, preserving historical live rows rather than rewriting them.
- Filters legacy live executors and position holds out of paper-mode recovery and executor listings.

The authenticated `GET /spectra/runtime` endpoint reports the effective mode, whether only paper connectors are enabled, whether the paper executor loop is running, and whether live connectors/dispatch are available. The Spectra interface must fail closed when this endpoint is unavailable or reports `LEGACY`. The HTTP guard runs before route dispatch. The connector allowlist is equally important: blocking REST writes alone would not stop a lazily created live connector from being used by an otherwise allowed paper order route.

## Enablement

Set the following in the API process environment before startup:

```dotenv
SPECTRA_PAPER_ONLY=true
```

Accepted boolean spellings are `true/false`, `1/0`, and `yes/no` (case-insensitive). Any other value fails startup rather than silently disabling the guard.

With the flag absent or false, the existing non-Spectra API behavior is unchanged. Do not use that legacy mode as a Spectra deployment authorization boundary.

## Hummingbot paper connector configuration

Hummingbot's current paper-trading documentation describes exchange connector names with the `_paper_trade` suffix (for example, `kraken_paper_trade`), configured through `paper_trade.paper_trade_exchanges` in `conf_client.yml`. The documentation lists Binance, KuCoin, Kraken, and Gate.io as enabled by default and describes a separate simulated balance configuration under `paper_trade.paper_trade_account_balance`.

Reference: https://hummingbot.org/client/global-configs/paper-trade/

The API container's exact `conf_client.yml` path and installed Hummingbot core revision still need to be verified. This repository currently installs the Hummingbot package without a pinned version because its API depends on unreleased core fields. Do not assume the latest public paper connector and the API's installed core are compatible until that dependency is pinned and the paper executor flow is tested.

## Deliberate limitations

- This mode intentionally disables live Hummingbot runtime startup. It therefore cannot be used to claim Hummingbot is already simulating paper orders.
- The allowed paper routes can execute only through connector names ending in `_paper_trade`; direct live connector names are rejected at connector creation and lookup boundaries.
- Hummingbot paper connectors still consume public market data; this is not an offline market-data simulator. The paper account must be provisioned with separate simulated balances and must never reuse live connector credentials.
- The first complete Spectra flow still needs Core authorization, exact simulated fill reconciliation, and separate paper-ledger accounting. Do not connect these routes to live connectors by weakening the suffix guard.
- This setting is defense in depth, not the future Core-issued signed dispatch receipt required for any separately approved live mode.

## Tests

`test/test_spectra_paper_guard.py` verifies the exact allowlist and representative execution, Gateway, Docker, bot, script, and account mutation blocks. Focused API CI also compiles `main.py` and the guard module.
