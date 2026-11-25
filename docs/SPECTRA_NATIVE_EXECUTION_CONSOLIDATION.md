# Spectra API Native Execution Consolidation Audit

Status: initial repository-backed audit; implementation not yet changed.
Working branch: `architecture/native-engine-consolidation`

## Findings

- The API runtime pins `hummingbot==20260922` in `environment.yml`.
- The trading router delegates `POST /trading/orders` to Hummingbot's `AccountsService.place_trade`; Hummingbot is already the actual execution framework.
- `UnifiedConnectorService` owns Hummingbot connector instances and paper-trade clock lifecycle.
- `utils/spectra_paper_guard.py` currently makes this branch paper-only: it requires exact paper flags, allows only `kraken_paper_trade`, rejects credential-shaped configuration, and blocks most mutating API routes.
- The current connector-service tests explicitly assert that live connector creation is rejected.

## Consolidation direction

Keep Hummingbot as the single owner of connectors, encrypted exchange credentials, connector startup, order placement/cancellation, order tracking, and executor lifecycle. Keep Spectra-specific policy in a narrow authorization middleware/service: validate signed, expiring, single-use Governor receipts and bind them to account, profile, connector, market, side, order type, amount, slippage and strategy origin before delegating to Hummingbot.

Avoid adding a second connector registry or execution engine. Spectra's API additions should be limited to authorization, audit events, health/diagnostics, and normalized reconciliation interfaces.

## Live capability design (not enabled)

Paper/live must be explicit isolated profiles. Live credentials must use Hummingbot's encrypted account credential mechanism, not Core environment variables. Live routes must remain default-deny until a human enables a separately scoped account/profile. Require bounded order and portfolio limits, independent capital authorization, kill switch, stale-market checks, idempotency, durable order receipts, fill/fee reconciliation, and restart recovery.

The API must never accept an instruction from a model or strategy loop as sufficient authority to activate live mode. No live connector is enabled and no real order is submitted by this audit.

## Work sequence

1. Trace every existing paper guard, dispatch receipt, order route, connector creation path, and Hummingbot account/credential service.
2. Identify which guard logic is genuinely Spectra-specific and retain it as a narrow authorization boundary.
3. Separate paper/live profiles without weakening paper controls or sharing credentials/state.
4. Add contract tests for both profiles, including negative tests proving paper credentials cannot access live connectors and live credentials cannot enter paper state.
5. Keep Hummingbot as the sole execution/order-state implementation and reconcile its events into Core.
