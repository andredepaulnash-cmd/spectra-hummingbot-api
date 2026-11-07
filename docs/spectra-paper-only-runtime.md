# Spectra paper-only API runtime

## Purpose

`SPECTRA_PAPER_ONLY=true` places this Hummingbot API process into a fail-closed, non-executing support mode. It is a containment setting for the Spectra local paper environment; it is not itself a paper exchange, market-data simulator, or Core authorization receipt.

## What the mode does

- Rejects every HTTP `POST`, `PUT`, `PATCH`, and `DELETE` mutation except four exact, reviewed history/query routes: `POST /executors/search`, `POST /trading/orders/search`, `POST /trading/trades`, and `POST /portfolio/history`.
- Uses an exact path allowlist. A new POST endpoint is blocked by default until reviewed.
- Does not initialize trading connectors or reconcile persisted active orders.
- Does not start/recover Hummingbot executors, bot/MQTT orchestration, market-data background feeds, or Gateway monitoring.
- Does not run Docker cleanup during shutdown.
- Leaves database startup available for persisted history reads.

The HTTP guard runs before route dispatch. The startup gate is equally important: blocking REST writes alone would not stop an already-persisted executor or bot from continuing to place orders.

## Enablement

Set the following in the API process environment before startup:

```dotenv
SPECTRA_PAPER_ONLY=true
```

Accepted boolean spellings are `true/false`, `1/0`, and `yes/no` (case-insensitive). Any other value fails startup rather than silently disabling the guard.

With the flag absent or false, the existing non-Spectra API behavior is unchanged. Do not use that legacy mode as a Spectra deployment authorization boundary.

## Deliberate limitations

- This mode intentionally disables live Hummingbot runtime startup. It therefore cannot be used to claim Hummingbot is already simulating paper orders.
- The four allowed POST routes are limited to persisted/local history or executor state; live market-data, account refresh, active-order, position, Gateway quote, and all execution/configuration writes remain blocked.
- The first Spectra paper simulator must live behind a separate Core-owned simulated ledger/adapter, or a separately verified Hummingbot paper connector that cannot reach live connectors. It must not be enabled by weakening this guard.
- This setting is defense in depth, not the future Core-issued signed dispatch receipt required for any separately approved live mode.

## Tests

`test/test_spectra_paper_guard.py` verifies the exact allowlist and representative execution, Gateway, Docker, bot, script, and account mutation blocks. Focused API CI also compiles `main.py` and the guard module.
