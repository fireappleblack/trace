#!/usr/bin/env bash
# flatten:begin
# repo-path: platform/mariadb/apply-mariadb.sh
# generated: 2026-06-06T16:30:04Z by flatten.py — do not edit this block
# flatten:end

# ─────────────────────────────────────────────────────────────────────────
# Create/refresh the MariaDB root Secret from the gitignored .secrets.env,
# then apply the MariaDB manifest — same out-of-band pattern as the trace DB.
#
#   cp platform/mariadb/_secrets_env.example platform/mariadb/.secrets.env
#   # edit .secrets.env — set MARIADB_ROOT_PASSWORD
#   ./platform/mariadb/apply-mariadb.sh
#
# Uses --from-env-file so the password is taken verbatim — characters like &
# are never interpreted by a shell (the footgun that bit the trace DB).
#
# PASSWORD DRIFT (same trap as Postgres, DEPLOYMENT.md §7): the root password
# is baked at first init on the PVC. Changing this Secret later does NOT change
# the password MariaDB already has. To rotate, change it INSIDE MariaDB too
# (ALTER USER 'root'@'localhost' IDENTIFIED BY ...). Never edit the Secret
# alone on an initialised volume.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS=mariadb
SECRETS_FILE="$HERE/.secrets.env"

if [[ ! -f "$SECRETS_FILE" ]]; then
  echo "Missing $SECRETS_FILE" >&2
  echo "  cp $HERE/_secrets_env.example $SECRETS_FILE   then edit it." >&2
  exit 1
fi

# Namespace first (idempotent).
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -

# Root Secret from the gitignored env file (idempotent; never in git).
kubectl create secret generic mariadb-root \
  --namespace "$NS" \
  --from-env-file="$SECRETS_FILE" \
  --dry-run=client -o yaml | kubectl apply -f -

# The engine (tuning ConfigMap + Service + StatefulSet; no secret in it).
kubectl apply -f "$HERE/mariadb.yaml"
kubectl -n "$NS" rollout status statefulset/mariadb

echo
echo ">> MariaDB applied in $NS."
echo "   Now re-run the backups helper so it starts backing MariaDB up:"
echo "     ./platform/backups/apply-backups.sh"
echo "   Provision per-site DBs with: ./wordpress/apply-site.sh (see wordpress/)."
