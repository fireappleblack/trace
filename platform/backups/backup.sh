#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# backup.sh — logical dumps of every cluster database → Oracle Object Storage
# ─────────────────────────────────────────────────────────────────────────
# Runs inside the cluster-backup image, on the schedule in backups.yaml.
# Shipped via a ConfigMap (apply-backups.sh creates it from this file), so it
# can be edited without rebuilding the image.
#
# What it does, in order:
#   1. Postgres  — pg_dump the trace DB (consistent snapshot), gzip, upload.
#   2. MariaDB   — per-database mariadb-dump (each WP site separately, so a
#                  restore is per-site), gzip, upload. SKIPPED cleanly if no
#                  MariaDB password is provided yet (backups-first: this runs
#                  and protects Postgres BEFORE MariaDB exists, and starts
#                  covering MariaDB automatically once it lands).
#   3. Retention — delete objects older than RETENTION_DAYS under each prefix.
#
# Design choices (honest about the trade-offs):
#   • Logical dumps, not block snapshots. Portable, restorable into a fresh
#     engine, and they survive a bad migration / accidental DROP — which
#     Longhorn replication does NOT. Longhorn volume backups (see
#     longhorn-backup-target.yaml) are a SEPARATE, complementary layer.
#   • Per-database MariaDB dumps (not --all-databases) so each site restores
#     independently and a corrupt one site can't block the others.
#   • The job attempts BOTH engines even if one fails, and exits non-zero if
#     EITHER failed — so a partial failure is visible in the Job status and
#     not silently swallowed.
#
# Connection params (host/port/user/db) are PLAIN env from the manifest — they
# are not secret. Only the passwords come from a Secret.
# ─────────────────────────────────────────────────────────────────────────
set -uo pipefail

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
REMOTE="oci:${OS_BUCKET}"          # rclone remote 'oci' is configured by env in backups.yaml
FAILED=0

log()  { echo "[$(date -u +%H:%M:%S)] $*"; }
fail() { echo "[$(date -u +%H:%M:%S)] ERROR: $*" >&2; FAILED=1; }

# ── 1. Postgres ───────────────────────────────────────────────────────────
# pg_dump is a consistent snapshot by default. PGPASSWORD is read from env.
backup_postgres() {
  log "Postgres: dumping ${PGDATABASE} from ${PGHOST}:${PGPORT}"
  local dest="${REMOTE}/postgres/${PGDATABASE}-${STAMP}.sql.gz"
  if pg_dump --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" \
             --no-owner --no-privileges "$PGDATABASE" \
       | gzip -9 \
       | rclone rcat "$dest"; then
    log "Postgres: uploaded ${dest}"
  else
    fail "Postgres dump/upload failed (${PGDATABASE})"
  fi
}

# ── 2. MariaDB (skipped until it exists) ────────────────────────────────────
# MYSQL_PWD is read from env by the mariadb client. We dump each non-system
# database separately. --single-transaction gives a consistent InnoDB dump
# without locking (WordPress is InnoDB).
backup_mariadb() {
  if [[ -z "${MYSQL_PWD:-}" ]]; then
    log "MariaDB: no password provided — skipping (not deployed yet). This is expected pre-MariaDB."
    return 0
  fi
  log "MariaDB: enumerating databases on ${MYSQL_HOST}"
  local dbs
  dbs="$(mariadb --host="$MYSQL_HOST" --user="$MYSQL_USER" --batch --skip-column-names \
          -e 'SHOW DATABASES;' \
          | grep -Ev '^(information_schema|performance_schema|mysql|sys)$')" || {
    fail "MariaDB: could not list databases"
    return 0
  }
  if [[ -z "$dbs" ]]; then
    log "MariaDB: reachable, but no site databases yet — nothing to dump."
    return 0
  fi
  local db dest
  while IFS= read -r db; do
    [[ -z "$db" ]] && continue
    dest="${REMOTE}/mariadb/${db}-${STAMP}.sql.gz"
    log "MariaDB: dumping ${db}"
    if mariadb-dump --host="$MYSQL_HOST" --user="$MYSQL_USER" \
                    --single-transaction --routines --events --triggers \
                    --databases "$db" \
         | gzip -9 \
         | rclone rcat "$dest"; then
      log "MariaDB: uploaded ${dest}"
    else
      fail "MariaDB dump/upload failed (${db})"
    fi
  done <<< "$dbs"
}

# ── 3. Retention ────────────────────────────────────────────────────────────
# Belt-and-braces on top of any bucket lifecycle rule (see README). Deletes
# dump objects older than RETENTION_DAYS under each prefix.
prune() {
  local prefix="$1"
  log "Retention: deleting ${prefix} objects older than ${RETENTION_DAYS}d"
  rclone delete --min-age "${RETENTION_DAYS}d" "${REMOTE}/${prefix}" 2>/dev/null \
    || log "Retention: nothing to prune under ${prefix} (or prefix absent)"
}

log "=== cluster backup ${STAMP} (retention ${RETENTION_DAYS}d) ==="
backup_postgres
backup_mariadb
prune postgres
prune mariadb

if [[ "$FAILED" -ne 0 ]]; then
  log "=== FINISHED WITH ERRORS — see above ==="
  exit 1
fi
log "=== backup complete ==="
