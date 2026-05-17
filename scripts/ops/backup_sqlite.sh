#!/usr/bin/env bash
set -euo pipefail

# Back up production SQLite db file from Docker volume mount.
# Usage:
#   DB_PATH=/var/lib/docker/volumes/app_data/_data/labelhub.db ./scripts/ops/backup_sqlite.sh

DB_PATH="${DB_PATH:-/var/lib/docker/volumes/app_data/_data/labelhub.db}"
OUT_DIR="${OUT_DIR:-./backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p "${OUT_DIR}"

if [[ ! -f "${DB_PATH}" ]]; then
  echo "Database file not found: ${DB_PATH}" >&2
  exit 1
fi

OUT_FILE="${OUT_DIR}/labelhub_${STAMP}.sqlite3.gz"
gzip -c "${DB_PATH}" > "${OUT_FILE}"

SHA_FILE="${OUT_FILE}.sha256"
sha256sum "${OUT_FILE}" > "${SHA_FILE}"

echo "Backup created: ${OUT_FILE}"
echo "Checksum file: ${SHA_FILE}"
