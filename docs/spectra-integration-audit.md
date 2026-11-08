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

### Spectra MCP allowlist — source path verified, with an important launch caveat

A follow-up traced the Condor spawner and the Spectra agent definition on Core PR #31:

- `agents/spectra/AGENT.md` explicitly allowlists read-only market/portfolio/history/executor-inspection tools, `create_grid_executor`, `create_dca_executor`, `stop_executor`, `delegate`, notification and the Spectra journal tools. It does **not** allow raw order placement, position executors, LP executors, DEX swaps/liquidity, bot/controller deployment, leverage changes, server administration, or arbitrary code execution.
- `condor.runtime.toolsets.build_mcp_servers_for_session` computes the profile and allowlist mutes, then passes `CONDOR_AGENT_SLUG=agent_slug` into the Hummingbot MCP subprocess environment and passes the same mutes to both MCP servers.
- `allowlist_mutes` subtracts every tool not named in the Spectra Agent's allowlist. For slug `spectra`, a missing Agent definition or an empty `tools` list mutes **every** known tool rather than widening access.
- The Hummingbot MCP server registers only the selected profile minus those mutes. Thus, for the normal Condor-spawned Spectra seat using this exact code and agent definition, the intended narrow MCP tool surface is enforced at registration.

Important caveat: the Hummingbot MCP server still defaults to `agent_slug=""` and `tool_profile="full"` when launched standalone or without the Condor spawner. In that mode the Spectra-only executor authorization is not activated and the full tool surface may register. Every production Spectra launch path must therefore prove the host-generated identity and restricted profile/mutes are present; no standalone/full-profile process may be connected to the Spectra API credentials.

This confirms the **MCP seat allowlist design** in source; it does not close the independent REST API routes documented below.

### Direct REST path — confirmed bypass of the MCP governor

The API exposes authenticated `POST /executors/` in `routers/executors.py`. `main.py` attaches HTTP Basic authentication to this router, but the route calls `ExecutorService.create_executor` directly. That service validates the executor configuration, prepares the market, instantiates the executor, starts it, and persists it; it does not accept or verify a Spectra capital proposal, governor receipt, breaker state, Kraken-only scope, or 1x Spectra authorization.

The API's own executor registry includes position, grid, DCA, arbitrage, TWAP, XEMM, order, and LP executors. Thus an API client with valid credentials can reach an execution path that is not protected by the MCP-side Spectra governor. Loopback binding reduces network exposure but does not close this authorization gap for local processes or other authenticated API clients.

**Required before any live-capital use:** establish one enforceable authorization boundary at or below the API's executor-creation service, or disable/restrict the direct executor-creation route for the Spectra deployment. Test direct REST attempts for every executor type, wrong connector, wrong leverage, missing/mismatched/expired/reused proposal, halted/missing breaker, and ambiguous API response. The MCP allowlist alone is not sufficient.

Also trace other API routes and bot/controller orchestration that can start execution; this review confirms the direct executor route but is not a proof that all other routes are closed.


### Additional authenticated execution surfaces — verified routes, authorization still unproven

A second pass found that `POST /executors/` is not the only way to cause trading activity. `main.py` applies the same HTTP Basic dependency to the following routers, but Basic authentication proves API identity only; it is not a Spectra capital-governor decision.

- **CEX order placement:** `POST /trading/orders` calls `AccountsService.place_trade` with caller-supplied account, connector, pair, side, amount, order type, price and position action. The route contains no proposal ID, governor receipt, breaker check or Spectra connector/intent validation.
- **DEX swaps:** `POST /gateway/swap/execute` and `POST /gateway/swap/execute-quote` call the Gateway swap path. The route requires Gateway online and validates connector-specific extra parameters, but the inspected route does not require a Spectra capital authorization.
- **Liquidity writes:** Gateway CLMM and AMM routers expose write operations including open/add/remove/close/collect-fees and add/remove-liquidity. They are execution-capable wallet operations; the inspected route declarations require Gateway online where shown, not a Spectra proposal or governor receipt.
- **Bot/controller start:** `POST /bot-orchestration/start-bot` publishes a `start` command for an active bot over MQTT. This can start a preconfigured strategy/controller; the route itself has no Spectra proposal check. The exact controller contents and downstream executor path must be traced before classifying each bot as trading-capable.

These are **confirmed execution-capable API surfaces**, not a claim that every underlying connector or Gateway path has been fully audited. No route-level Spectra gate was present in the inspected handlers. Until lower-level enforcement is demonstrated with adversarial tests, treat every one as a potential route around the MCP-only governor. A localhost bind or Tailscale network boundary reduces reachability but does not provide capital authorization against local authenticated clients.

**Required acceptance tests:** for each route family, prove that missing, mismatched, expired, reused and wrong-scope proposals are rejected before any connector/Gateway/MQTT dispatch; prove halted or missing breaker state fails closed; prove only the approved Kraken USD spot Grid/DCA 1x scope can dispatch in a Spectra deployment; and prove ordinary non-Spectra deployments retain their separately documented behavior. For DEX swaps and liquidity operations, either define an explicit Spectra-governed policy and receipt model or disable those write routes in the Spectra runtime. For bot starts, verify controller allowlists and recursively trace every controller's execution calls.

This is a source-level finding. No requests were sent to the running API, no wallets or exchange accounts were accessed, and no code path was activated.

### Additional bot deployment paths — confirmed container-start dispatch

A further trace of the bot orchestration path found two additional authenticated write routes:

- **`POST /bot-orchestration/deploy-v2-controllers`** generates a `v2_with_controllers.py` script configuration and calls `DockerService.create_hummingbot_instance`.
- **`POST /bot-orchestration/deploy-v2-script`** calls the same Docker service with the requested script deployment.

The Docker service's `create_hummingbot_instance` ends in Docker SDK `containers.run(..., detach=True, ...)`. Docker's `run` operation creates and starts the container; these are not merely configuration-registration routes. The controller deployment can therefore start a Hummingbot container configured with the supplied controller list, and the script deployment can start a container with the supplied script. Both routes are included under the API's HTTP Basic `auth_user` dependency in `main.py`; the inspected route handlers do not require a Spectra proposal, governor receipt, breaker check, or Spectra-specific controller/script allowlist before the Docker dispatch.

Treat these as execution-capable deployment surfaces in a Spectra runtime. The controller and script payloads must be recursively reviewed and restricted to the approved Spectra execution boundary, or these routes must be disabled for the Spectra deployment. A controller/script allowlist applied only to the MCP tools does not govern direct API deployment.

### Core branch topology — integration must remain staged

The Core work is not one linear PR stack:

- **PR #31 → #32 → #33** is a sequential protected-LIMIT / cash-and-retirement / installed-runtime-repair line. PR #33 adds the five-file Hummingbot Core overlay and a source-bound build recipe.
- The PR #38 dependency-preparation branch is a descendant of the PR #33 source line (its base is one commit after PR #33); it adds runtime dependency preparation and read-only installed-source attestation. It does not finish the image or Bazzite acceptance.
- **PR #40** is a separate branch from `spectra-core-phase2`. It adds recovery accounting, selected-recovery ownership locks, dust lifecycle, and partial-attempt handling. It diverges from PR #31: the compared heads are 5 commits ahead and 6 behind their common base.
- **PR #42** is based on PR #40 and adds weekly-reversal / next-entry research. Its PR diff contains 19 Core paths, 48 test paths and 29 research paths; its next-entry bridges are explicitly default-off paper components and the adaptive-reversal mechanics are paper-only. This is not production activation or evidence of profitability.

The PR #31 and #40 heads modify the same high-risk files, including `capital_governor.py`, `economic_position.py`, `executor_create.py`, `partial_recycle.py`, and `vcap_runtime.py`, but their unique APIs encode different invariants. PR #31 uniquely carries cash-authority/submission-claim and terminal-retirement APIs; PR #40 uniquely carries selected-recovery locks/proposal scopes and partial-attempt runtime guards. A blind merge or cherry-pick can drop one side's capital ownership protections. The integration must select a reviewed base and explicitly port/retest each invariant, not treat green CI as proof that the branches are interchangeable.

All six Core PR workflow runs (#31, #32, #33, #38, #40 and #42) were observed completed successfully in GitHub Actions. These are branch-specific CI results, not a combined-branch test and not live-readiness evidence.

### Runtime evidence — partial success, release blockers remain

PR #38's recorded disposable Python 3.12 trial installed 197 hashed Python artifacts (267,835,299 bytes), passed `pip check`, passed the bounded compiled data-module ABI check, and passed the PR #33 installed-source guard in both resolved and offline-reconstruction virtual environments. That is useful evidence for those exact disposable environments.

The same receipt explicitly records that the complete inherited environment is **not** verified: the original `eip712-structs` extra was excluded from the successful trial; the installed `msgpack-python 0.5.6` and `msgpack 1.2.3` distributions still claim three identical module paths; a proposed sixth packaging overlay is not applied; the complete native Conda environment is not locked; no immutable base-image digest or final API image digest exists; and Bazzite installation is not verified. The cleanup proposal requires a fresh six-overlay build and new wheel identity. Preserve the current five-overlay identity; do not silently modify it.

The authenticated Docker router also exposes `POST /docker/start-container/{container_name}`, which calls `DockerService.start_container` and invokes Docker `container.start()` for an existing stopped container. The service performs a name lookup and start; the inspected path does not restrict the target to API-managed Hummingbot instances. It can therefore reactivate any stopped container the API's Docker daemon credentials can access, including a previously configured Hummingbot instance, without going through the MCP governor. Treat container start/restart as a privileged execution dispatch and require a managed-container allowlist, Spectra identity, controller allowlist, and governor boundary before enabling it in the Spectra runtime. The route is not an authorization-safe substitute for the dedicated start-bot path.

### Deeper service trace — direct dispatch confirmed in the inspected API path

The route-to-service trace confirms that several findings are not limited to missing checks in the HTTP handlers:

- **Direct executor API:** `POST /executors/` passes only `executor_config`, `account_name`, and `controller_id` to `ExecutorService.create_executor`. That service validates the executor config and market readiness, constructs the executor, registers it, and calls `executor.start()`. The inspected route request and service call have no proposal ID, governor receipt, breaker token, or Spectra authorization context.
- **Direct exchange orders:** `POST /trading/orders` calls `AccountsService.place_trade`. After account/connector/rule/size checks, that method directly invokes `connector.buy(...)` or `connector.sell(...)`. These are exchange-order validation checks, not a Spectra capital-governor authorization.
- **Direct Gateway swaps:** `POST /swap/execute` resolves a wallet and calls `GatewayClient.execute_swap`, which sends a POST to Gateway's `trading/{router,clmm,amm}/execute-swap` surface. `/swap/execute-quote` similarly calls `execute_quote` and posts to Gateway's router quote-execution surface. The route-level Gateway-online dependency only checks reachability.
- **Bot start:** `POST /bot-orchestration/start-bot` passes caller-supplied `script` and `conf` values into `BotsOrchestrator.start_bot`, which publishes the `start` command over MQTT. This is a control-plane dispatch, not a governor-checked execution request.

The code paths inspected above show no Spectra governor authorization before these connector, Gateway, executor-start, or MQTT dispatch calls. This is stronger evidence than the earlier route-handler-only review, but it is still a bounded source trace: any separately injected process-level policy or external network restriction must be verified in the final deployment. Until such an independent enforcement point is demonstrated and covered by negative tests, treat these paths as ungoverned for the Spectra threat model.

### Additional account-risk and container-control writes

The route inventory also found authenticated operations that can change trading exposure or the execution environment:

- `POST /trading/{account_name}/{connector_name}/leverage` delegates to `AccountsService.set_leverage` and then `PerpetualTradingService.set_leverage`.
- `POST /trading/{account_name}/{connector_name}/position-mode` delegates to `AccountsService.set_position_mode` and then the perpetual connector service.
- `POST /trading/{account_name}/{connector_name}/orders/{client_order_id}/cancel` directly invokes the connector cancellation API.
- Docker routes can stop, remove, prune exited containers, and pull images. These are operationally privileged even where they do not themselves submit an order.

The inspected leverage and position-mode route/service chain has no visible Spectra policy receipt or risk-governor check. The cancellation endpoint is a direct connector mutation and must be included in an explicit order-management policy (for example, which bot/order identity may be cancelled). Docker cleanup, removal and image-pull operations should be admin-only and separated from the trading controller. Do not expose the Hummingbot API's broad administrative surface as the Spectra agent's tool surface.

### Recommended enforcement boundary — Core-issued, API-verified dispatch receipt

The current MCP authorization is valuable but is not sufficient as the sole boundary while the Hummingbot REST API remains independently callable. The API itself must reject execution unless Spectra Core has authorized the exact operation.

Recommended design for a later implementation (not yet built):

1. **Core remains the sole policy authority.** It evaluates breaker state, proposal identity, capital reservations, position ownership, allowed strategy, account/connector/pair, amount, leverage, slippage and policy version. It commits/reserves the capital claim before issuing a dispatch receipt.
2. **Core issues a short-lived signed receipt** binding the exact operation: unique receipt/nonce, proposal ID, intent, account, connector, market, operation/executor type, canonical configuration digest, capital amount, leverage, permitted order/position action, slippage/fee bounds, issue/expiry times and policy version. No wildcard account, connector, pair, or amount.
3. **The API verifies the receipt at the dispatch boundary** using a pinned public key and a durable one-time receipt ledger. It rejects expired, malformed, wrong-scope, altered-payload, unknown-key, duplicate, already-consumed, or mismatched receipts before connector, Gateway, MQTT, executor, or Docker dispatch.
4. **Ambiguous outcomes reconcile; they do not retry blindly.** Persist receipt consumption and dispatch state before external calls; after timeout/crash, reconcile by receipt ID and exchange/Gateway order or transaction evidence. A repeated request returns the recorded outcome or a reconciliation-required state, never a second order.
5. **Every alternate write route is either covered by the same verifier or disabled.** This includes direct trading orders, leverage/position mode, executor creation, DEX swaps/liquidity, bot start/deploy, Docker container start, and any controller/script deployment path. Reads may remain separately available with least-privilege credentials.

Required negative tests at the API boundary: no receipt; invalid signature; expired receipt; replay; receipt for another account/connector/pair; config digest changed after signing; amount or leverage above scope; unsupported executor; HALTED Core state; wrong policy version; and a receipt consumed by a competing concurrent request. Assert that each case is rejected **before** any connector/Gateway/MQTT/Docker call. Positive tests must prove exactly one dispatch for one valid receipt, including timeout/restart/reconciliation cases.

Until this boundary exists, safest deployment containment is to keep the Hummingbot API private to the trusted local process, deny the Condor/agent direct network route to its write endpoints, and disable nonessential execution/deployment routers. Network isolation is defense in depth, not a replacement for API-side receipt verification.

The public request schemas reinforce this boundary finding: `CreateExecutorRequest` contains `account_name`, `controller_id`, and an arbitrary `executor_config` dictionary, but no proposal ID or governor receipt. `TradeRequest` contains account, connector, pair, side, amount, order type, price and position action, but no Spectra authorization field. The controller ID is an attribution label, not proof of capital approval. The deployment request models similarly accept a credentials profile, image and script/controller configuration without a Core-issued dispatch receipt.

### Image provenance and deployment path — build is not part of deploy

The API repository's current deployment contract has a reproducibility gap:

- `docker-compose.yml` selects `image: hummingbot/hummingbot-api:latest` and has no `build:` section for the API service.
- The Makefile's `build` target builds the local image as `hummingbot/hummingbot-api:latest`.
- The Makefile's `deploy` target runs `docker compose up -d` (with an optional Tailscale overlay) but does not depend on or invoke `make build`.
- Therefore `make deploy` can start/pull the mutable registry `latest` image rather than the source currently checked out. A successful deploy does not prove the local source was built into the running image.
- The Dockerfile starts from mutable `continuumio/miniconda3` in both stages, and `environment.yml` contains unpinned Conda dependencies plus unpinned `hummingbot`. The API CI workflow currently compiles a small accounting subset and runs focused tests; it does not build or attest the production Docker image.

Recommended correction (not yet implemented): build a unique immutable image tag from the checked-out source commit and exact dependency lock; require compose to use that exact tag/digest; make deploy refuse when the expected image digest is absent or mismatched; record the source SHA, Core overlay SHA, base-image digest, dependency artifact hashes, final image digest and test report in a machine-readable build attestation. Never deploy `latest` for the Spectra runtime. Keep the current deployment path unchanged until a tested replacement is ready.

### High-severity deployment trust boundary — caller-selected image runs with credentials and host networking

The deployment trace found an additional container-isolation concern:

- Both `V2ScriptDeployment` and `V2ControllerDeployment` accept an `image` string, defaulting to `hummingbot/hummingbot:latest`; the inspected models validate instance/credential/config names but do not enforce an image allowlist or immutable digest.
- `DockerService.create_hummingbot_instance` passes `config.image` directly to Docker SDK `containers.run`.
- The created container receives read-write mounts for the instance `conf` directory (which contains the copied credentials profile), scripts/controllers, data and logs; it uses `network_mode="host"`.
- The API compose service itself mounts `/var/run/docker.sock`, giving the API Docker-daemon control.

This does not establish an unauthenticated remote exploit: the deployment routes are behind the API's HTTP Basic authentication. It does mean that any caller holding those API credentials and access to the deployment route can request a caller-selected container image that is started with access to the instance credential files and host networking. For Spectra, this is an unacceptable agent-facing privilege boundary unless tightly constrained.

Required containment: hard-code or strictly allowlist reviewed Hummingbot image digests; reject arbitrary registries/tags; separate deployment administration from the agent identity; never mount exchange credentials into an image that is not the approved Hummingbot build; and avoid exposing Docker-socket control to the general agent API. Test that an unapproved image/digest is rejected before Docker is called. Review host-network requirements and reduce container privileges/network reachability where feasible. This is a source-level risk finding, not a claim that the current API credentials have been compromised.

## 4. Integration and test plan

1. **Local sync:** fetch API `origin/main`; verify the current local branch is still the reported ancestor; fast-forward only. Preserve the modified compose file and both untracked backups. No reset/clean.
2. **Compatibility:** select and complete the exact pinned Core overlay build; resolve PR #38 blockers; pin Python/Conda/Pip dependencies; remove the mutable image path; ensure `deploy` cannot pull an unreviewed upstream image.
3. **Authorization:** close the direct REST bypass; fail closed on missing Spectra process identity; verify allowlist registration for tick, attended agent, coordinator, ACP and standalone launch paths.
4. **Tests:** run the API focused CI and full relevant API tests; run Core governor/executor/bridge suites; add API service-level authorization tests and adversarial bypass tests; build and inspect the exact image; run offline Bazzite smoke tests with synthetic exchange I/O only.
5. **Acceptance:** record source SHAs, overlay manifest SHA, dependency lock hashes, image digest, test reports, startup compatibility evidence, and proof that no live exchange client/order dispatch is enabled.

## Safety boundary

This audit makes no strategy profitability claim and grants no execution authority. No merges to the default branch, deployment, wallet access, exchange order, or live-trading activation are part of this audit.

### Additional launch-path finding — checked-in standalone MCP configuration

A cross-repository source check found a concrete standalone Hummingbot MCP launch path in the Core repository's checked-in `.mcp.json`: it runs `uv run python -m mcp_servers.hummingbot_api` with no `--profile`, no `--agent-slug`, and an empty environment object. Core's `mcp_servers/hummingbot_api/settings.py` explicitly defines the standalone default as `full`, and `get_settings()` parses that default when no profile flag is supplied. The server registers the resolved profile at startup.

This configuration may be intended for local developer use; it is not proof that production currently launches this way. It is nevertheless a real alternate path that must be accounted for in acceptance. It must never receive Spectra production API credentials or be treated as a governed Spectra agent seat. Production launch should be restricted to the supervised Condor spawner, which passes the host-generated agent identity, explicit profile and mutes. Remove or clearly segregate the static full-profile entry from any production runtime configuration, and add a startup test that refuses Spectra credentials when the process has no host-generated Spectra identity or explicit restricted profile.

The new Core documentation-only integration map records this and the PR #31/#40 shared-file port plan: [PR #43 — recovery-safety integration map](https://github.com/andredepaulnash-cmd/spectra-finance-core/pull/43). It is a draft and does not merge or change runtime code.


### Complete execution-capable REST route inventory — follow-up source pass

The following route families were enumerated from API main. main.py attaches HTTP Basic authentication to each listed router; that proves API identity only, not a Spectra governor authorization. This inventory distinguishes external mutations from operational/configuration writes.

| Route | Effect / dispatch | Spectra governor evidence in inspected handler |
|---|---|---|
| POST /executors/ | Creates, starts and persists a Hummingbot executor | None; direct call to ExecutorService.create_executor |
| POST /executors/{executor_id}/stop | Stops an executor; keep_position controls whether exposure may be closed | None in route; requires a governed stop/exit policy |
| POST /trading/orders | Direct connector buy/sell | None; calls AccountsService.place_trade |
| POST /trading/{account}/{connector}/orders/{client_order_id}/cancel | Direct connector order cancellation | None; calls account service cancellation |
| POST /trading/{account}/{connector}/leverage | Changes perpetual leverage | None in inspected route/service path |
| POST /trading/{account}/{connector}/position-mode | Changes perpetual position mode | None in inspected route/service path |
| POST /gateway/swap/execute | Executes a wallet swap | Gateway-online check only; calls GatewayClient.execute_swap |
| POST /gateway/swap/execute-quote | Executes a previously quoted wallet swap | Gateway-online check only; calls GatewayClient.execute_quote |
| POST /gateway/clmm/open, /add, /remove, /close, /collect-fees | Opens, funds, reduces, closes CLMM positions or collects fees | Gateway-online check only on these write routes; no Core receipt in inspected handlers |
| POST /gateway/clmm/create-pool | Creates a CLMM pool | Gateway-online check; no Core receipt in inspected handler |
| POST /gateway/amm/add-liquidity, /remove-liquidity | Adds/removes AMM liquidity | Gateway-online check; no Core receipt in inspected handlers |
| POST /gateway/amm/create-pool | Creates and seeds an AMM pool | Gateway-online check; no Core receipt in inspected handler |
| POST /bot-orchestration/start-bot | Sends MQTT start command with caller-supplied script/config | None in inspected handler |
| POST /bot-orchestration/deploy-v2-controllers, /deploy-v2-script | Creates and starts a Hummingbot container | None; calls Docker service |
| POST /docker/start-container/{container_name} | Starts any named stopped container visible to the Docker service | No Spectra identity/managed-container receipt check in inspected handler |
| POST /docker/pull-image/ | Pulls an image through Docker service | Administrative supply-chain mutation; must not be agent-accessible |
| POST /gateway/start, /stop, /restart | Starts/stops/restarts Gateway | Operational control; not a trading-governor check |
| POST /accounts/gateway/wallet/set-default | Changes which wallet is selected by default for a chain | Gateway-online check only; no Core receipt in inspected handler |
| POST /accounts/add-credential/{account}/{connector}, /delete-credential/{account}/{connector} | Adds/removes exchange connector credentials | Administrative secret mutation; keep outside agent surface |

Other write routes update controller/script source and configuration, connector/API-key/network/token/pool settings, account records, or Docker/container state. These may not submit a trade immediately, but can change what code, credentials, wallet, network, image, or strategy is used by a later start. They must be separated from the Spectra agent's least-privilege runtime and protected as administrative operations.

The following routes are read/quote/history surfaces rather than dispatches in the inspected handlers: /gateway/swap/quote, /gateway/clmm/quote-position, /gateway/amm/quote-liquidity, and position/order/trade search and history endpoints. They can remain candidates for a read-only tool profile, subject to normal data-access controls. Quote creation must not be confused with quote execution.

**Implementation consequence:** do not patch only /executors/ or only the MCP wrapper. First define a deployment mode in which the API's execution boundary is explicit. Every external mutation must either (a) verify a Core-issued, one-time, scope-bound dispatch receipt immediately before dispatch, or (b) be disabled for the Spectra runtime. The receipt verifier must cover executor start/stop, direct CEX orders/cancel, leverage and position mode, Gateway swaps/liquidity, bot start/deploy, Docker container start and wallet selection. Administrative writes (credentials, arbitrary controller/script edits, image pulls, Gateway/API-key/network configuration and Docker management) should be unavailable to the Spectra agent entirely and exposed only through a separate operator/admin channel.

No source files implementing runtime behavior were changed by this follow-up. This route inventory is based on GitHub source inspection of API main; no running API endpoint, Docker daemon, Gateway, wallet, exchange account, MQTT broker or container was contacted.


### Stop/exit authority — the Spectra-approved stop tool also dispatches a financial mutation

The Core Spectra Agent definition explicitly includes stop_executor as a permitted safety/control tool. Its server wrapper calls executors_tools.stop_executor, which calls the Hummingbot API client's executor stop endpoint. The tool documentation is explicit that stopping an executor moves real funds; keep_position=false is the default and may close the position, while keep_position=true retains spot exposure where supported. For LP executors, stopping always closes the on-chain LP position; keep_position controls whether the resulting net token change is retained or swapped back.

The API route POST /executors/{executor_id}/stop passes executor_id and keep_position directly to ExecutorService.stop_executor. The inspected route has no Core-issued receipt, Spectra ownership check, proposal binding, or caller-to-executor ownership authorization. Therefore this is not just an administrative stop: it is an execution-capable exit path that the Spectra Agent is intentionally allowed to invoke, and it must be governed as a distinct EXIT/RELEASE action.

Required policy: a stop receipt must bind the exact executor ID, owning account/connector/pair, permitted close behavior, and any permitted keep-position behavior. The API must verify that the executor belongs to the Spectra-owned set and that the receipt is single-use before stop dispatch. An emergency stop may use a separate narrowly scoped, fail-safe authority, but must not become a generic way to close arbitrary executors or bypass ownership/accounting. Tests must cover unknown IDs, other-agent executors, already-terminated executors, keep_position true/false, LP close/swap semantics, replay, and ambiguous stop results. Until this exists, do not treat the current stop tool as governor-enforced merely because it is in the Spectra Agent allowlist.
