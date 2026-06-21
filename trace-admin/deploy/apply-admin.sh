#!/usr/bin/env bash
# flatten:begin
# repo-path: trace-admin/deploy/apply-admin.sh
# generated: 2026-06-21T17:35:52Z by flatten.py — do not edit this block
# flatten:end

# Create/update the trace-admin secret out-of-band (never committed).
#
# Reads deploy/.secrets.env (gitignored) and applies it as the
# `trace-admin-secrets` Secret in the `trace` namespace. Uses --from-env-file
# so values are taken literally (no shell interpolation footguns).
set -euo pipefail
cd "$(dirname "$0")"

NS=trace
ENV_FILE=.secrets.env

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: $ENV_FILE not found. Copy .secrets.env.example to .secrets.env and fill it in." >&2
  exit 1
fi

kubectl -n "$NS" create secret generic trace-admin-secrets \
  --from-env-file="$ENV_FILE" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Applied trace-admin-secrets to namespace $NS."
