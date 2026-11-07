# Spectra API integration audit

**Audit snapshot:** API `main` at `84426ffbf9ba09522b4444664f9770236205ae29`; Spectra Core `spectra-core-phase2` at `6e894fa9c2b55384d0f6120f41ca91892e1fe207`. This is a source review only. No runtime, exchange, wallet, or live-trading actions were performed.

## 1. API repository reconciliation

The local API base previously reported by the operator is `39f0630d13da75fb49e397874b962225adc78b4e`. GitHub `main` is a strict descendant: **33 commits ahead, 0 behind**, with the local commit as merge base. The comparison reports 13 changed paths, covering the Spectra API CI workflow, executor/position-hold accounting, order/trade provenance, and their contract tests.

The operator's local `docker-compose.yml` edits and two untracked backup files are not represented in this GitHub comparison. They must remain untouched during the local fast-forward. The remote 33-commit range does not modify `docker-compose.yml`, so the tracked local compose diff and untracked backups can be retained while fast-forwarding; verify the worktree before and after. Do not reset, clean, stash-drop, or overwrite these files.

Local-only changes previously reported:
- `security_opt: - label=disable`
- `./bots:/hummingbot-api/bots:z` instead of the unlabelled bind mount
- untracked `docker-compose.yml.bak.*` copies

The `label=disable` setting weakens SELinux container separation and should be evaluated separately from the `:z` bind-mount relabel. Preserve it during synchronization, but do not treat it as an approved security fix.

## 2. API / Hummingbot Core / image compatibility

### Confirmed blockers

- `docker-compose.yml` selects `hummingbot/hummingbot-api:latest`; it does not declare a local build for the repository Dockerfile.
- The Makefile's `build` target also tags the generic mutable `hummingbot/hummingbot-api:latest`. The `deploy` target invokes `docker compose up -d` and does not depend on `build`; a deploy can therefore pull the upstream mutable image instead of the reviewed local source.
- `environment.yml` installs `hummingbot` without a version or source commit. This does not bind the API to a known Hummingbot Core tree.
- `utils/core_compatibility.py` has an empty `REQUIRED_CORE_SURFACE`; the startup guard currently checks no fields. Its docstring still describes an unpinned package and a historical missing-field hazard, so the empty list is not a compatibility proof.
- The repository Dockerfile copies the API source into an image but does not itself establish the Spectra Core overlay/build identity.
- The current `spectra-api.yml` workflow compiles six selected source files and runs four dependency-light contract/wiring test files. It does not build the runtime image, install the complete Hummingbot dependency stack, run the full API test suite, or attest Bazzite compatibility.

### Candidate pinned build contract already present elsewhere

Core PR #33 contains a reviewed source-build recipe binding:
- API source `84426ffbf9ba09522b4444664f9770236205ae29`
- Hummingbot Core source `9af100d6822da7d2d0291a906c730ef172284ee2`
- an explicit overlay manifest checksum and immutable Miniconda base-image digest

However, PR #33 remains a draft and explicitly does not attest a compiled wheel, final image digest, installed Bazzite runtime, or live activation. Core PR #38 also records unresolved packaging blockers: missing `eip712-structs` in the trial image, overlapping `msgpack-python` / `msgpack` wheel files, and no complete API image or Bazzite acceptance. Therefore this candidate recipe is a source contract, not a deployable artifact yet.

**Required before deployment:** resolve the PR #38 packaging blockers; build from the exact reviewed API/Core/overlay identities using an immutable base-image digest; record the resulting image digest; make Compose and `deploy` consume that exact image; and prove the installed package identities at startup. Do not use `latest`.

## 3. Executor authorization boundary

### MCP path

In Spectra Core's MCP executor creation path, `_authorize_spectra_execution` is called before the Hummingbot API client creates an executor. When `settings.agent_slug == "spectra"`, it checks breaker state, restricts executor types to grid/DCA, restricts connector to Kraken, requires 1x leverage and a matching proposal ID/intent/amount, commits the exact governor claim before dispatch, and reconciles the executor receipt afterward. Ambiguous outcomes are retained and must not be blindly retried.

The gate is conditional: `mcp_servers/hummingbot_api/settings.py` defaults `agent_slug` to an empty string, and the standalone MCP profile defaults to `full`. In that mode, `_authorize_spectra_execution` returns without applying the Spectra gate. A Spectra deployment must prove every agent MCP process is spawned with the Spectra identity and its fail-closed tool allowlist; standalone/full-profile execution must not be mistaken for the Spectra-authorized seat.

The shared Condor toolset code documents a fail-closed Spectra allowlist rule: a missing or empty Spectra `agent.tools` list mutes every known tool. That behavior still needs an installed-runtime test against the actual Spectra agent definition and every supported launch/backend path.

### Direct REST path — confirmed bypass of the MCP governor

The API exposes authenticated `POST /executors/` in `routers/executors.py`. `main.py` attaches HTTP Basic authentication to this router, but the route calls `ExecutorService.create_executor` directly. That service validates the executor configuration, prepares the market, instantiates the executor, starts it, and persists it; it does not accept or verify a Spectra capital proposal, governor receipt, breaker state, Kraken-only scope, or 1x Spectra authorization.

The API's own executor registry includes position, grid, DCA, arbitrage, TWAP, XEMM, order, and LP executors. Thus an API client with valid credentials can reach an execution path that is not protected by the MCP-side Spectra governor. Loopback binding reduces network exposure but does not close this authorization gap for local processes or other authenticated API clients.

**Required before any live-capital use:** establish one enforceable authorization boundary at or below the API's executor-creation service, or disable/restrict the direct executor-creation route for the Spectra deployment. Test direct REST attempts for every executor type, wrong connector, wrong leverage, missing/mismatched/expired/reused proposal, halted/missing breaker, and ambiguous API response. The MCP allowlist alone is not sufficient.

Also trace other API routes and bot/controller orchestration that can start execution; this review confirms the direct executor route but is not a proof that all other routes are closed.

## 4. Integration and test plan

1. **Local sync:** fetch API `origin/main`; verify the current local branch is still the reported ancestor; fast-forward only. Preserve the modified compose file and both untracked backups. No reset/clean.
2. **Compatibility:** select and complete the exact pinned Core overlay build; resolve PR #38 blockers; pin Python/Conda/Pip dependencies; remove the mutable image path; ensure `deploy` cannot pull an unreviewed upstream image.
3. **Authorization:** close the direct REST bypass; fail closed on missing Spectra process identity; verify allowlist registration for tick, attended agent, coordinator, ACP and standalone launch paths.
4. **Tests:** run the API focused CI and full relevant API tests; run Core governor/executor/bridge suites; add API service-level authorization tests and adversarial bypass tests; build and inspect the exact image; run offline Bazzite smoke tests with synthetic exchange I/O only.
5. **Acceptance:** record source SHAs, overlay manifest SHA, dependency lock hashes, image digest, test reports, startup compatibility evidence, and proof that no live exchange client/order dispatch is enabled.

## Safety boundary

This audit makes no strategy profitability claim and grants no execution authority. No merges to the default branch, deployment, wallet access, exchange order, or live-trading activation are part of this audit.