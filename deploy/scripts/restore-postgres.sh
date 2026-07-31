#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <backup.dump>" >&2
  exit 2
fi
if [[ -z "${TARGET_DATABASE_URL:-}" ]]; then
  echo "TARGET_DATABASE_URL is required" >&2
  exit 2
fi
if [[ "${CONFIRM_TARGET_DATABASE_URL:-}" != "$TARGET_DATABASE_URL" ]]; then
  echo "Refusing restore: CONFIRM_TARGET_DATABASE_URL must exactly match TARGET_DATABASE_URL" >&2
  exit 2
fi

backup="$1"
if [[ ! -f "$backup" ]]; then
  echo "Backup not found: $backup" >&2
  exit 2
fi

pg_restore --list "$backup" >/dev/null
pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error \
  --dbname="$TARGET_DATABASE_URL" "$backup"

echo "Restore completed: $backup"
