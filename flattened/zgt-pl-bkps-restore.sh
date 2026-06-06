#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# restore.sh — restore ONE logical dump from Object Storage into a database.
# ─────────────────────────────────────────────────────────────────────────
# A backup you have never restored is a guess, not a backup. The backups
# decision (DECISIONS.md) explicitly requires ONE TESTED RESTORE. Use this to
# do that test, and keep it as the break-glass procedure.
#
# It runs a one-shot pod IN-CLUSTER (so it can reach the databases and reuse
# the same secrets and image as the backup job). It does NOT modify anything
# until you confirm.
#
# Usage:
#   # list what's in the bucket:
#   ./platform/backups/restore.sh list postgres
#   ./platform/backups/restore.sh list mariadb
#
#   # restore a specific object into a target database:
#   ./platform/backups/restore.sh postgres trace-20260605T020700Z.sql.gz <target_db>
#   ./platform/backups/restore.sh mariadb  wp_example-20260605T020700Z.sql.gz
#
# SAFETY: restore into a SCRATCH database first to validate (e.g. create
# `trace_restore_test` and restore into that), compare row counts, THEN decide
# whether to promote. Restoring over a live DB is destructive.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

NS=platform-backups
IMAGE="ghcr.io/fireappleblack/cluster-backup:v0.1.0"
ENGINE="${1:-}"; OBJECT="${2:-}"; TARGET="${3:-}"

usage() { sed -n '2,30p' "$0"; exit 1; }
[[ -z "$ENGINE" ]] && usage

run() {
  # Run a command in a transient pod that inherits the backup env (rclone +
  # DB creds) via the same secrets the CronJob uses.
  kubectl -n "$NS" run "restore-$(date -u +%s)" --rm -i --restart=Never \
    --image="$IMAGE" \
    --overrides='{
      "spec": {
        "imagePullSecrets": [{"name":"ghcr-pull"}],
        "containers": [{
          "name":"restore","image":"'"$IMAGE"'","stdin":true,"tty":false,
          "command":["/bin/bash","-c","'"$1"'"],
          "envFrom":[
            {"secretRef":{"name":"backup-object-store"}},
            {"secretRef":{"name":"backup-db-passwords"}}
          ],
          "env":[
            {"name":"RCLONE_CONFIG_OCI_TYPE","value":"s3"},
            {"name":"RCLONE_CONFIG_OCI_PROVIDER","value":"Other"},
            {"name":"RCLONE_CONFIG_OCI_ACCESS_KEY_ID","value":"$(OS_ACCESS_KEY_ID)"},
            {"name":"RCLONE_CONFIG_OCI_SECRET_ACCESS_KEY","value":"$(OS_SECRET_ACCESS_KEY)"},
            {"name":"RCLONE_CONFIG_OCI_ENDPOINT","value":"$(OS_ENDPOINT)"},
            {"name":"RCLONE_CONFIG_OCI_REGION","value":"$(OS_REGION)"},
            {"name":"PGHOST","value":"trace-postgres.trace.svc.cluster.local"},
            {"name":"PGUSER","value":"trace"},
            {"name":"MYSQL_HOST","value":"mariadb.mariadb.svc.cluster.local"},
            {"name":"MYSQL_USER","value":"root"}
          ]
        }]
      }
    }'
}

case "$ENGINE" in
  list)
    PREFIX="${OBJECT:-}"
    [[ -z "$PREFIX" ]] && { echo "usage: restore.sh list <postgres|mariadb>"; exit 1; }
    run 'rclone lsl oci:${OS_BUCKET}/'"$PREFIX"' | sort'
    ;;
  postgres)
    [[ -z "$OBJECT" || -z "$TARGET" ]] && { echo "usage: restore.sh postgres <object.sql.gz> <target_db>"; exit 1; }
    echo "About to restore postgres/$OBJECT INTO database '$TARGET' on trace-postgres."
    echo "The target DB must already exist and should be a SCRATCH db for testing."
    read -rp "Type the target db name again to confirm: " c; [[ "$c" == "$TARGET" ]] || { echo "aborted"; exit 1; }
    run 'set -e; rclone cat oci:${OS_BUCKET}/postgres/'"$OBJECT"' | gunzip \
         | psql --host=$PGHOST --username=$PGUSER --dbname='"$TARGET"' -v ON_ERROR_STOP=1; \
         echo RESTORE_OK'
    ;;
  mariadb)
    [[ -z "$OBJECT" ]] && { echo "usage: restore.sh mariadb <object.sql.gz>"; exit 1; }
    echo "About to restore mariadb/$OBJECT into MariaDB (the dump carries its own"
    echo "CREATE DATABASE/USE, from --databases). For a SAFE test, edit the dump's"
    echo "database name first, or restore on a throwaway MariaDB."
    read -rp "Type YES to proceed: " c; [[ "$c" == "YES" ]] || { echo "aborted"; exit 1; }
    run 'set -e; rclone cat oci:${OS_BUCKET}/mariadb/'"$OBJECT"' | gunzip \
         | mariadb --host=$MYSQL_HOST --user=$MYSQL_USER; echo RESTORE_OK'
    ;;
  *) usage ;;
esac
