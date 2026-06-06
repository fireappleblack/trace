#!/usr/bin/env bash
# flatten:begin
# repo-path: platform/backups/apply-backups.sh
# generated: 2026-06-06T16:30:04Z by flatten.py — do not edit this block
# flatten:end

# ─────────────────────────────────────────────────────────────────────────
# Set up cluster backups, out-of-band, in the right order:
#   1. namespace platform-backups
#   2. backup-object-store Secret  — from gitignored .secrets.env (OCI S3 keys)
#   3. backup-db-passwords  Secret  — DERIVED from the live DB secrets so there
#      is ONE source of truth. PG password always; MariaDB root password only
#      if the mariadb secret already exists (backups-first: PG is protected
#      now, MariaDB folds in automatically the moment it lands — just re-run
#      this script after deploying MariaDB).
#   4. backup-script ConfigMap     — from backup.sh (edit + re-run to update)
#   5. ghcr-pull Secret             — copied from the trace namespace
#   6. kubectl apply -f backups.yaml
#
#     cp platform/backups/_secrets_env.example platform/backups/.secrets.env
#     # edit .secrets.env
#     ./platform/backups/apply-backups.sh
#
# Why temp env-files + --from-env-file rather than --from-literal: the password
# is taken verbatim, so characters like & ^ @ are never interpreted by the
# shell — the same footgun that bit the trace DB secret. Temp files are 0600
# and shredded on exit.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS=platform-backups
SECRETS_FILE="$HERE/.secrets.env"

TRACE_NS=trace
TRACE_DB_SECRET=trace-db          # key: POSTGRES_PASSWORD
MARIA_NS=mariadb
MARIA_SECRET=mariadb-root         # key: MARIADB_ROOT_PASSWORD

if [[ ! -f "$SECRETS_FILE" ]]; then
  echo "Missing $SECRETS_FILE" >&2
  echo "  cp $HERE/_secrets_env.example $SECRETS_FILE   then edit it." >&2
  exit 1
fi

TMP="$(mktemp -d)"
chmod 700 "$TMP"
cleanup() { find "$TMP" -type f -exec shred -u {} + 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT

# 1. Namespace (idempotent).
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -

# 2. Object Storage credentials (verbatim from the gitignored file).
kubectl create secret generic backup-object-store \
  --namespace "$NS" \
  --from-env-file="$SECRETS_FILE" \
  --dry-run=client -o yaml | kubectl apply -f -

# 3. backup-db-passwords — derived from the live source secrets.
DBPW_FILE="$TMP/dbpw.env"
: > "$DBPW_FILE"; chmod 600 "$DBPW_FILE"

PGPW="$(kubectl -n "$TRACE_NS" get secret "$TRACE_DB_SECRET" \
          -o jsonpath='{.data.POSTGRES_PASSWORD}' 2>/dev/null | base64 -d || true)"
if [[ -z "$PGPW" ]]; then
  echo "ERROR: could not read POSTGRES_PASSWORD from $TRACE_NS/$TRACE_DB_SECRET." >&2
  echo "       Is the trace DB secret present? (./trace-server/deploy/apply-db.sh)" >&2
  exit 1
fi
printf 'PGPASSWORD=%s\n' "$PGPW" >> "$DBPW_FILE"

if MARIAPW="$(kubectl -n "$MARIA_NS" get secret "$MARIA_SECRET" \
               -o jsonpath='{.data.MARIADB_ROOT_PASSWORD}' 2>/dev/null | base64 -d)" \
   && [[ -n "$MARIAPW" ]]; then
  printf 'MYSQL_PWD=%s\n' "$MARIAPW" >> "$DBPW_FILE"
  echo ">> MariaDB root password found — MariaDB backups ENABLED."
else
  echo ">> MariaDB secret not found yet — backups will cover Postgres only."
  echo "   Re-run this script after deploying MariaDB to start backing it up."
fi

kubectl create secret generic backup-db-passwords \
  --namespace "$NS" \
  --from-env-file="$DBPW_FILE" \
  --dry-run=client -o yaml | kubectl apply -f -

# 4. The backup script as a ConfigMap (edit backup.sh + re-run to update it).
kubectl create configmap backup-script \
  --namespace "$NS" \
  --from-file=backup.sh="$HERE/backup.sh" \
  --dry-run=client -o yaml | kubectl apply -f -

# 5. Copy the GHCR pull secret from the trace namespace (private image).
#    Skip this if you made the cluster-backup package public.
if kubectl -n "$TRACE_NS" get secret ghcr-pull >/dev/null 2>&1; then
  kubectl -n "$TRACE_NS" get secret ghcr-pull -o yaml \
    | sed "s/namespace: $TRACE_NS/namespace: $NS/" \
    | kubectl -n "$NS" apply -f -
  echo ">> ghcr-pull copied into $NS."
else
  echo ">> No ghcr-pull in $TRACE_NS. If the cluster-backup image is private,"
  echo "   create the pull secret in $NS before the CronJob can run."
fi

# 6. The CronJob.
kubectl apply -f "$HERE/backups.yaml"

echo
echo ">> Backups installed in $NS."
echo "   Run one NOW (don't wait for the schedule) to confirm it works:"
echo "     kubectl -n $NS create job --from=cronjob/db-backup db-backup-manual"
echo "     kubectl -n $NS logs -f job/db-backup-manual"
echo "   Then verify objects landed in the bucket, and run a TEST RESTORE"
echo "   (restore.sh) before you trust it. See README.md."
