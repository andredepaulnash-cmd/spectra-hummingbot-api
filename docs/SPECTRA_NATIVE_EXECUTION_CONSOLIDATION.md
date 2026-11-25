# Spectra API Native Execution Consolidation Audit

Status: repository-backed architecture decision; implementation track in progress.
Working branch: `architecture/native-engine-consolidation`

## Verified Hummingbot foundation

- API `environment.yml` pins `hummingbot==20260922`; this is the execution-core version to preserve until compatibility tests justify a deliberate upgrade.
- `routers/trading.py` delegates `POST /trading/orders` to Hummingbot's `AccountsService.place_trade`.
- `UnifiedConnectorService` is already the single owner of Hummingbot trading and data connector instances. It manages connector locks, connector startup, and the native PaperTradeExchange clock.
- `AccountsService` already uses Hummingbot's `ETHKeyFileSecretManger` and connector config/key helpers. The existing Hummingbot credential machinery should remain authoritative; do not create a second credential vault in Spectra.
- `utils/spectra_paper_guard.py` currently forces paper-only operation: exact paper flags, only `kraken_paper_trade`, rejection of credential-shaped config, and a narrow allowlist for mutating routes.
- `UnifiedConnectorService`, `AccountsService`, route dependencies, and tests contain paper-only assumptions. Live support requires a complete, consistent profile-aware policy—not just removing the guard.
- The order router itself is already a Hummingbot-native execution entry point. No separate Spectra order engine is needed in this repository.

## Consolidation direction

Keep Hummingbot as the single owner of connectors, encrypted exchange credentials, connector startup, order placement/cancellation, order tracking, account balances, and executor lifecycle. Keep Spectra-specific policy in a narrow authorization boundary: validate signed, expiring, single-use Governor receipts and bind them to profile, account, connector, market, side, order type, quantity/notional, slippage, and strategy origin before delegating to Hummingbot.

Avoid adding a second connector registry or execution engine. API additions should be limited to:
- profile-aware authorization and route policy;
- read-only profile readiness and diagnostics;
- durable dispatch receipts and audit events;
- normalized order/fill/fee reconciliation for Core;
- explicit profile switching protocol that refuses to switch while orders or portfolio state are unresolved.

## Selectable PAPER / LIVE profiles

PAPER and LIVE are both supported operating profiles, selected by Spectra—not by a model prompt or an arbitrary request header.

- PAPER resolves only to the configured Hummingbot paper connector/account and simulated balances.
- LIVE resolves only to an explicitly configured Hummingbot live connector/account whose credentials are present in Hummingbot's encrypted credential store.
- Profile identity is included in every Governor receipt and checked again at the API boundary. A PAPER receipt cannot authorize LIVE; a LIVE receipt cannot authorize PAPER.
- Connector name, account name, profile, and environment namespace are validated together. A client cannot choose a connector independently of the active profile.
- Paper and live account/portfolio state are separately namespaced. There is no automatic migration or netting of positions/balances when switching.
- A switch is rejected if orders are pending, fills are unreconciled, or the target profile is not ready.
- The same Hummingbot trading route and connector lifecycle are used in both profiles. No custom live-order client is to be added.
- Existing paper-only routes remain the default until the full profile contract and tests are implemented. Do not weaken current protections in an intermediate commit.

## Required implementation work

1. Trace all uses of `paper_only_enabled`, `configured_paper_connectors`, `require_paper_trade_connector`, and `should_block_paper_mutation` across startup, dependencies, connector creation, account configuration, and routes.
2. Replace scattered environment checks with one typed, centrally loaded execution-profile policy. Keep the paper-only release behavior unchanged.
3. Add profile-bound dispatch receipt validation and ensure the API derives account/connector from the profile, never from an untrusted client-supplied connector.
4. Keep credential creation/storage/retrieval inside Hummingbot's existing encrypted configuration mechanism. Do not pass exchange secrets through Spectra Core env vars or logs.
5. Add tests for paper and live profile resolution, credential separation, receipt profile mismatch, unauthorized connector mismatch, route allowlists, account isolation, pending-order mode-switch refusal, and Hummingbot order/fill reconciliation.
6. Keep Hummingbot as the only order/executor lifecycle implementation.

## Non-goals and preservation

- Do not change the pinned Hummingbot version as part of the first profile refactor.
- Do not weaken paper protections or modify the existing release branch.
- Do not load user exchange credentials, activate LIVE, or submit real orders during development.
- Do not claim live capability is complete until the profile-aware connector lifecycle and all contract tests pass.
