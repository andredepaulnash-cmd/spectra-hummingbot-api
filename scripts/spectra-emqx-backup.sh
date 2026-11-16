#!/usr/bin/env bash
# Preserve EMQX before repair: try native export, then archive every broker mount.
# The broker is stopped only for the raw-volume snapshot and is restarted afterward.
# No volume is deleted, renamed, pruned, or replaced.

set -Eeuo pipefail
cd "$(cd -P "$(dirname "$0")/.." && pwd)" || exit 1

BROKER_CONTAINER="$(printenv SPECTRA_BROKER_CONTAINER)"
[ -n "$BROKER_CONTAINER" ] || BROKER_CONTAINER="spectra-alpha-hummingbot-broker"
BACKUP_ROOT="$(printenv SPECTRA_BACKUP_DIR)"
[ -n "$BACKUP_ROOT" ] || BACKUP_ROOT="../backups"

if ! command -v podman >/dev/null 2>&1; then
  echo "ERROR: podman is required" >&2
  exit 1
fi
if ! podman inspect "$BROKER_CONTAINER" >/dev/null 2>&1; then
  echo "ERROR: broker container not found: $BROKER_CONTAINER" >&2
  exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%S%NZ)"
backup_dir="$BACKUP_ROOT/emqx-$timestamp"
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"

copy_private() {
  local source="$1" name="$2"
  if [ -f "$source" ]; then
    cp -p "$source" "$backup_dir/$name"
    chmod 600 "$backup_dir/$name"
  fi
}

copy_private .env api.env
copy_private .emqx/auth-bootstrap.csv auth-bootstrap.csv
copy_private emqx/acl.conf acl.conf
copy_private docker-compose.alpha.yml docker-compose.alpha.yml
copy_private docker-compose.yml docker-compose.yml

was_running=false
if podman inspect "$BROKER_CONTAINER" 2>/dev/null |
  python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin)[0].get("State",{}).get("Running") else 1)' \
  >/dev/null 2>&1; then
  was_running=true
fi

stopped=false
restart_broker() {
  if [ "$stopped" = true ]; then
    echo "Restarting broker after backup..."
    podman start "$BROKER_CONTAINER" >/dev/null || {
      echo "WARNING: broker backup completed, but automatic restart failed." >&2
      echo "Start it with: podman start $BROKER_CONTAINER" >&2
      return 1
    }
    stopped=false
  fi
}
trap restart_broker EXIT

export_ok=false
if [ "$was_running" = true ]; then
  if podman exec "$BROKER_CONTAINER" /opt/emqx/bin/emqx ctl status >/dev/null 2>&1; then
    if podman exec "$BROKER_CONTAINER" /opt/emqx/bin/emqx ctl data export \
      >"$backup_dir/emqx-data-export.log" 2>&1; then
      archive="$(sed -n 's/.*"\(data\/backup\/emqx-export-[^"]*\.tar\.gz\)".*/\1/p' \
        "$backup_dir/emqx-data-export.log" | tail -1)"
      if [ -n "$archive" ] && \
        podman cp "$BROKER_CONTAINER:/opt/emqx/$archive" "$backup_dir/$(basename "$archive")" \
        >/dev/null 2>&1; then
        chmod 600 "$backup_dir/$(basename "$archive")"
        export_ok=true
      fi
    fi
  fi
fi

if [ "$was_running" = true ]; then
  echo "Stopping broker briefly for a consistent raw-volume snapshot..."
  podman stop --time 30 "$BROKER_CONTAINER" >/dev/null
  stopped=true
fi

podman inspect "$BROKER_CONTAINER" |
  python3 -c '
import json,sys
d=json.load(sys.stdin)[0]
for m in d.get("Mounts",[]):
    print("{}\t{}\t{}\t{}".format(
        m.get("Type",""), m.get("Name",""), m.get("Source",""),
        m.get("Destination","")
    ))
' >"$backup_dir/mounts.tsv"

volume_count=0
while IFS="$(printf '\t')" read -r mount_type volume_name source destination; do
  [ -n "$source" ] || continue
  safe_name="$(printf '%s' "$destination" | sed 's#^/##; s#/#_#g')"
  if [ "$mount_type" = "volume" ] && [ -n "$volume_name" ]; then
    mountpoint="$(podman volume inspect "$volume_name" --format '{{.Mountpoint}}')"
  else
    mountpoint="$source"
  fi
  if [ -d "$mountpoint" ]; then
    tar -czf "$backup_dir/$safe_name.tar.gz" -C "$mountpoint" .
  elif [ -f "$mountpoint" ]; then
    cp -p "$mountpoint" "$backup_dir/$safe_name"
    chmod 600 "$backup_dir/$safe_name"
  else
    echo "WARNING: mount source unavailable; skipped $destination ($mountpoint)" >&2
  fi
  volume_count=$((volume_count + 1))
done <"$backup_dir/mounts.tsv"

if [ "$stopped" = true ]; then
  restart_broker
fi
trap - EXIT

cat >"$backup_dir/manifest.txt" <<EOF
created_utc=$timestamp
broker_container=$BROKER_CONTAINER
container_was_running=$was_running
native_emqx_export=$export_ok
raw_mounts_archived=$volume_count
old_volumes_were_not_deleted_or_modified=true
EOF
chmod 600 "$backup_dir/manifest.txt"

if [ "$volume_count" -eq 0 ]; then
  echo "ERROR: no broker mounts were archived; inspect $backup_dir" >&2
  exit 1
fi

echo
echo "EMQX BACKUP COMPLETE"
echo "Backup: $backup_dir"
echo "Native EMQX export: $export_ok"
echo "Raw broker mounts archived: $volume_count"
echo "Original volumes preserved; no reset or replacement performed."
