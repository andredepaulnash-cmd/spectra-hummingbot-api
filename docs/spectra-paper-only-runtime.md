# Spectra paper-only API runtime

## Purpose

`SPECTRA_PAPER_ONLY=true` places this Hummingbot API process into a fail-closed, non-executing support mode. It is a containment setting for the Spectra local paper environment; it is not itself a paper exchange, market-data simulator, or Core authorization receipt.

## What the mode does

- Allows only a reviewed set of paper order, executor, account-read, portfolio, and market-data POST routes. Gateway, wallet, credential-management, bot orchestration, script, Docker, and every unreviewed mutation route remain blocked.
- Uses exact route patterns. A new POST endpoint is blocked by default until reviewed.
- Initializes only connector names ending in `_paper_trade`; the connector service independently rejects live CEX, perpetual, and Gateway connector names, including lazy connector creation.
- Starts the Hummingbot executor control loop and account service only against those paper connectors, so simulated orders can be created and managed without starting live connectors.
- Does not construct or start the Docker-backed bot/MQTT orchestrator, Gateway monitoring, Docker actions, or market-data background feeds. The Docker-backed orchestrator is not instantiated at all in paper mode, so the API container does not need the host Docker/Podman socket. Paper connectors own their public market feed.
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


## Pinned Hummingbot core and local API image

The Spectra API environment pins the Hummingbot Python package to `20260922`, and startup independently checks the installed package metadata against that exact version. A mismatch or missing package stops startup instead of silently running against a different executor/connector surface.

The Docker Compose service builds this repository's Dockerfile into the local `spectra-finance/hummingbot-api:local` image. `make deploy` now depends on `make build`, so deployment does not silently pull the mutable upstream `hummingbot/hummingbot-api:latest` image instead of the Spectra-reviewed source. The Miniconda base image and the remaining transitive Python/Conda dependencies are still mutable; a complete digest lock and image attestation remain future hardening work.

The selected package version is an available Hummingbot PyPI release (20260922). It is a compatibility baseline for the Spectra paper runtime, not proof of the full connector integration; the expanded local/API-image paper test remains required before the product can be called operational.


## Core-issued API dispatch receipts

Every mutating request under the execution/deployment route families (`/executors`, `/trading`, `/gateway`, `/bots`, `/docker`, `/controllers`, and `/scripts`) is now guarded by a short-lived Ed25519 receipt signed by Spectra Core. Search/read routes remain available. The API verifies the HTTP method, normalized path, canonical request-body digest, executor-config digest, proposal/account/connector/market/intent/amount scope, policy version, issue/expiry times, and signature before the route runs.

The API stores consumed receipt IDs in a durable SQLite ledger under `bots/data/spectra_dispatch_receipts.sqlite3` (or `SPECTRA_DISPATCH_RECEIPT_DB`). A receipt is single-use; a replay is rejected. If a request times out after receipt consumption, reconcile the original proposal/dispatch rather than retrying with the same receipt.

Configure `SPECTRA_DISPATCH_PUBLIC_KEY` with the base64url-encoded 32-byte Ed25519 public key generated for the matching Spectra Core private key. Set the same `SPECTRA_DISPATCH_POLICY_VERSION` in Core and API (default `spectra-policy-v1`), and keep `SPECTRA_PAPER_ONLY=true` and `SPECTRA_ALLOW_LIVE_EXECUTION=false` in both processes. The API defaults to paper-only and refuses a false paper-mode setting without a separate future live-mode authorization. `SPECTRA_REQUIRE_CORE_RECEIPTS` defaults to true. If the public key or receipt ledger is unavailable, protected writes fail closed. The Core process must keep its private key local and supply the receipt header on the exact authorized API request. Do not place the private key in this API repository, Docker image, logs, or chat.

The API verifier accepts exact-scope receipts for governed executor creation and executor stop/position-hold operations. Stop receipts bind the exact executor ID in the route, the `keep_position` body, and the owner account/connector/market scope. Until the matching Core-side signer and request-header integration are installed, protected writes intentionally remain unavailable. This is a safety interlock, not a completed end-to-end integration.
