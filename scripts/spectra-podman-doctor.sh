#!/usr/bin/env bash
# Read-only health summary for Spectra Alpha on Bazzite/Podman.
# Never starts, stops, recreates, resets, prunes, or modifies containers/volumes.

set -o pipefail
cd "$(cd -P "$(dirname "$0")/.." && pwd)" || exit 1

API_CONTAINER="$(printenv SPECTRA_API_CONTAINER)"
BROKER_CONTAINER="$(printenv SPECTRA_BROKER_CONTAINER)"
PG_CONTAINER="$(printenv SPECTRA_PG_CONTAINER)"
API_URL="$(printenv SPECTRA_API_URL)"
[ -n "$API_CONTAINER" ] || API_CONTAINER="spectra-alpha-hummingbot-api"
[ -n "$BROKER_CONTAINER" ] || BROKER_CONTAINER="spectra-alpha-hummingbot-broker"
[ -n "$PG_CONTAINER" ] || PG_CONTAINER="spectra-alpha-hummingbot-postgres"
[ -n "$API_URL" ] || API_URL="http://127.0.0.1:8000"

OK=0; WARN=0; FAIL=0
row() {
  case "$1" in
    ok) printf 'OK   %-22s %s\n' "$2" "$3"; OK=$((OK+1));;
    warn) printf 'WARN %-22s %s\n' "$2" "$3"; WARN=$((WARN+1));;
    *) printf 'FAIL %-22s %s\n' "$2" "$3"; FAIL=$((FAIL+1));;
  esac
}
has_cmd() { command -v "$1" >/dev/null 2>&1; }
env_get() {
  local key="$1" line
  [ -f .env ] || return 0
  line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?$key[[:space:]]*=" .env 2>/dev/null | tail -1)" || return 0
  [ -n "$line" ] || return 0
  printf '%s' "$line" | cut -d= -f2- | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//; s/^"//; s/"$//; s/^'\''//; s/'\''$//'
}
exists() { podman inspect "$1" >/dev/null 2>&1; }
running() {
  podman inspect "$1" 2>/dev/null |
    python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin)[0].get("State",{}).get("Running") else 1)' \
    >/dev/null 2>&1
}
state() {
  podman inspect "$1" 2>/dev/null |
    python3 -c 'import json,sys; s=json.load(sys.stdin)[0].get("State",{}); h=s.get("Health") or {}; print("{} / health={}".format(s.get("Status","?"),h.get("Status","unknown")))' \
    2>/dev/null || echo "not found"
}

echo
echo "SPECTRA ALPHA — READ-ONLY PODMAN DOCTOR"
echo "Project: $(pwd)"
echo

if has_cmd podman; then row ok "Podman" "$(podman --version 2>/dev/null)"
else row fail "Podman" "command not found"; exit 1; fi
if has_cmd podman-compose; then row ok "podman-compose" "$(podman-compose --version 2>/dev/null | head -1)"
elif podman compose version >/dev/null 2>&1; then row ok "Podman Compose" "$(podman compose version 2>/dev/null | head -1)"
else row warn "Podman Compose" "not found; container inspection remains available"; fi
if [ -r /etc/os-release ] && grep -qi bazzite /etc/os-release; then
  row ok "Host OS" "Bazzite detected; no host package changes"
else row warn "Host OS" "Bazzite not detected"; fi

free_kb="$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {print $4}')"
if [[ "$free_kb" =~ ^[0-9]+$ ]]; then
  free_gb=$((free_kb/1024/1024))
  if [ "$free_gb" -lt 15 ]; then row warn "Disk space" "$free_gb GiB free"
  else row ok "Disk space" "$free_gb GiB free"; fi
fi

if [ -f .env ]; then
  API_USER="$(env_get USERNAME)"; API_PASS="$(env_get PASSWORD)"
  BROKER_USER="$(env_get BROKER_USERNAME)"; BROKER_PASS="$(env_get BROKER_PASSWORD)"
  PAPER_ONLY="$(env_get SPECTRA_PAPER_ONLY)"
  PAPER_CONNECTORS="$(env_get SPECTRA_PAPER_CONNECTORS)"
  ALLOW_LIVE="$(env_get SPECTRA_ALLOW_LIVE_EXECUTION)"
  if [ -n "$API_USER" ] && [ -n "$API_PASS" ]; then row ok "API credentials" "present; values hidden"
  else row fail "API credentials" "USERNAME/PASSWORD missing"; fi
  if [ -n "$BROKER_USER" ] && [ -n "$BROKER_PASS" ]; then row ok "Broker credentials" "present; values hidden"
  else row warn "Broker credentials" "BROKER_USERNAME/BROKER_PASSWORD missing"; fi
  if [ "$PAPER_ONLY" = "true" ]; then row ok "Paper-only config" "SPECTRA_PAPER_ONLY=true"
  else row fail "Paper-only config" "SPECTRA_PAPER_ONLY is not explicitly true"; fi
  case ",$PAPER_CONNECTORS," in
    *,kraken_paper_trade,*) row ok "Paper connector" "Kraken paper connector configured";;
    *) row warn "Paper connector" "kraken_paper_trade not in SPECTRA_PAPER_CONNECTORS";;
  esac
  if [ "$ALLOW_LIVE" = "false" ] || [ -z "$ALLOW_LIVE" ]; then row ok "Live gate" "false/unset"
  else row fail "Live gate" "SPECTRA_ALLOW_LIVE_EXECUTION is not false"; fi

  if [ -f .emqx/auth-bootstrap.csv ]; then
    dir_mode="$(stat -c '%a' .emqx 2>/dev/null || echo unknown)"
    file_mode="$(stat -c '%a' .emqx/auth-bootstrap.csv 2>/dev/null || echo unknown)"
    header="$(head -1 .emqx/auth-bootstrap.csv 2>/dev/null)"
    csv_user="$(sed -n '2{s/,.*//;p;}' .emqx/auth-bootstrap.csv 2>/dev/null)"
    csv_pass="$(sed -n '2{s/^[^,]*,\([^,]*\),.*/\1/p;}' .emqx/auth-bootstrap.csv 2>/dev/null)"
    if [ "$dir_mode" = "700" ] && [ "$file_mode" = "644" ] \
      && [ "$header" = "user_id,password,is_superuser" ] \
      && [ "$csv_user" = "$BROKER_USER" ] && [ "$csv_pass" = "$BROKER_PASS" ]; then
      row ok "EMQX bootstrap" "permissions and credentials match; values hidden"
    else row warn "EMQX bootstrap" "check .emqx=700, CSV=644, header and credentials"; fi
  else row warn "EMQX bootstrap" ".emqx/auth-bootstrap.csv missing"; fi
else
  row fail ".env" "missing"
  API_USER=""; API_PASS=""
fi

for name in "$API_CONTAINER" "$BROKER_CONTAINER" "$PG_CONTAINER"; do
  if exists "$name"; then
    current_state="$(state "$name")"
    if running "$name"; then
      case "$current_state" in
        *"health=unhealthy"*) row fail "$name" "$current_state";;
        *"health=starting"*) row warn "$name" "$current_state";;
        *) row ok "$name" "$current_state";;
      esac
    else
      row fail "$name" "$current_state"
    fi
  else row fail "$name" "container not found"; fi
done

if running "$PG_CONTAINER"; then
  if podman exec "$PG_CONTAINER" pg_isready >/dev/null 2>&1; then
    row ok "PostgreSQL" "pg_isready accepts connections"
  else row fail "PostgreSQL" "pg_isready failed"; fi
fi

if running "$BROKER_CONTAINER"; then
  if podman exec "$BROKER_CONTAINER" /opt/emqx/bin/emqx ctl status >/dev/null 2>&1; then
    row ok "EMQX node" "emqx ctl status succeeded"
  else row fail "EMQX node" "emqx ctl status failed"; fi
  mounts="$(podman inspect "$BROKER_CONTAINER" 2>/dev/null |
    python3 -c 'import json,sys; d=json.load(sys.stdin)[0]; print(", ".join("{}={}".format(m.get("Name") or m.get("Source","bind"),m.get("Destination","?")) for m in d.get("Mounts",[])))' 2>/dev/null || true)"
  [ -n "$mounts" ] && row ok "EMQX mounts" "$mounts"
  errors="$(podman logs --tail 250 "$BROKER_CONTAINER" 2>&1 |
    grep -Ei 'not_a_log_file|LATEST\.LOG|mnesia|bootstrap.*(fail|error)|failed to import|CRITICAL|ERROR' |
    tail -6 | tr '\n' ';' | cut -c1-220)"
  if [ -n "$errors" ]; then row warn "EMQX errors" "$errors"
  else row ok "EMQX errors" "no recent Mnesia/bootstrap errors detected"; fi
fi

if has_cmd curl && [ -n "$API_USER" ] && [ -n "$API_PASS" ]; then
  if curl -fsS --max-time 4 -u "$API_USER:$API_PASS" "$API_URL/openapi.json" >/dev/null 2>&1; then
    row ok "Hummingbot API" "authenticated /openapi.json HTTP 200"
    runtime="$(curl -fsS --max-time 4 -u "$API_USER:$API_PASS" "$API_URL/spectra/runtime" 2>/dev/null || true)"
    if [ -n "$runtime" ] && printf '%s' "$runtime" | python3 -c '
import json,sys
d=json.load(sys.stdin)
ok=(d.get("mode")=="PAPER_ONLY" and d.get("paper_only") is True
    and d.get("paper_connectors_only") is True
    and d.get("live_dispatch_available") is False
    and any(str(x).endswith("/kraken_paper_trade") for x in d.get("paper_connectors", [])))
sys.exit(0 if ok else 1)
' >/dev/null 2>&1; then
      row ok "Spectra runtime" "paper-only; Kraken paper connector active; live dispatch unavailable"
    else row fail "Spectra runtime" "paper-only contract not confirmed"; fi
  else row fail "Hummingbot API" "authenticated /openapi.json probe failed"; fi
else row warn "Hummingbot API" "curl or API credentials unavailable; probes skipped"; fi

echo
printf 'Summary: %s passed, %s warnings, %s failures\n' "$OK" "$WARN" "$FAIL"
echo "Read-only: no containers, volumes, credentials, or files were changed."
[ "$FAIL" -eq 0 ]
