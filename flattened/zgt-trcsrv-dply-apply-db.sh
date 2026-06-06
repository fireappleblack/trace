#!/usr/bin/env bash
# flatten:begin
# repo-path: trace-server/deploy/apply-db.sh
# generated: 2026-06-06T16:30:04Z by flatten.py — do not edit this block
# flatten:end

# ─────────────────────────────────────────────────────────────────────────
# Create/refresh the database Secret from the gitignored .secrets.env, then
# apply the Postgres manifest — in the right order so the StatefulSet finds
# its credentials. Run once to set up, or again any time you rotate the
# password (it upserts the Secret, then you restart Postgres to pick it up).
#
#   ./trace-server/deploy/apply-db.sh
#
# Why --from-env-file (not `source` + --from-literal): kubectl reads the file
# itself, so the password is taken verbatim. A shell `source` of the file
# would try to EXECUTE characters like & in the password — exactly the class
# of bug that bit us before. This keeps any password safe with zero escaping.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS=trace
SECRETS_FILE="$HERE/.secrets.env"

if [[ ! -f "$SECRETS_FILE" ]]; then
  echo "Missing $SECRETS_FILE" >&2
  echo "  cp $HERE/.secrets.env.example $SECRETS_FILE   then edit it." >&2
  exit 1
fi

# Namespace first (idempotent upsert).
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -

# Secret from the gitignored env file (idempotent upsert; never in git).
kubectl create secret generic trace-db \
  --namespace "$NS" \
  --from-env-file="$SECRETS_FILE" \
  --dry-run=client -o yaml | kubectl apply -f -

# The rest of the database (no secret in it).
kubectl apply -f "$HERE/postgres.yaml"
kubectl -n "$NS" rollout status statefulset/trace-postgres

echo ">> database + secret applied. (If you ROTATED the password, recreate the"
echo "   DB so initdb picks it up — see the note printed by README.)"
