#!/usr/bin/env bash
set -euo pipefail

# Restore compressed SQLite backup.
# Usage:
#   BACKUP_FILE=./backups/labelhub_20260505_120000.sqlite3.gz DB_PATH=/var/lib/docker/volumes/app_data/_data/labelhub.db ./scripts/ops/restore_sqlite.sh

BACKUP_FILE="${BACKUP_FILE:-}"
DB_PATH="${DB_PATH:-/var/lib/docker/volumes/app_data/_data/labelhub.db}"

if [[ -z "${BACKUP_FILE}" ]]; then
  echo "Set BACKUP_FILE path to a .sqlite3.gz backup file." >&2
  exit 1
fi
if [[ ! -f "${BACKUP_FILE}" ]]; then
  echo "Backup file not found: ${BACKUP_FILE}" >&2
  exit 1
fi

mkdir -p "$(dirname "${DB_PATH}")"
TMP="${DB_PATH}.tmp_restore"
gunzip -c "${BACKUP_FILE}" > "${TMP}"
mv "${TMP}" "${DB_PATH}"
chmod 600 "${DB_PATH}" || true

echo "Restore completed to ${DB_PATH}"
