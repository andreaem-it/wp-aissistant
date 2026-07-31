#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is required" >&2
  exit 2
fi

backup_dir="${BACKUP_DIR:-./backups}"
retention_days="${BACKUP_RETENTION_DAYS:-14}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"
target="$backup_dir/wp-aissistant-$timestamp.dump"
temporary="$target.partial"

cleanup() { rm -f "$temporary"; }
trap cleanup EXIT

pg_dump --format=custom --compress=9 --no-owner --no-acl --file="$temporary" "$DATABASE_URL"
pg_restore --list "$temporary" >/dev/null
mv "$temporary" "$target"
trap - EXIT

if [[ "$retention_days" =~ ^[0-9]+$ ]] && (( retention_days > 0 )); then
  find "$backup_dir" -type f -name 'wp-aissistant-*.dump' -mtime "+$retention_days" -delete
fi

echo "$target"
