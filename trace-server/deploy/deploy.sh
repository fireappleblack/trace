#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# One-command build + push + rollout for the trace app, with versioned tags.
#
#   ./trace-server/deploy/deploy.sh v0.4.0
#
# Each call builds a uniquely-tagged image, pushes it to GHCR, and rolls the
# Deployment to it. Unique tags mean Kubernetes always sees a real change and
# does a clean rollout — no scale-to-zero, no stale-pod guessing, no "is this
# :latest the new one?".
#
# Run it from anywhere; it locates the project root relative to itself.
#
# Prerequisites (one-time):
#   • podman on this Mac, logged in to GHCR:
#       echo $CR_PAT | podman login ghcr.io -u fireappleblack --password-stdin
#     (CR_PAT = a CLASSIC PAT with write:packages — fine-grained tokens are
#      not accepted by GHCR.)
#   • kubectl pointed at the cluster.
#   • The cluster has the GHCR pull secret (the package is private):
#       kubectl -n trace create secret docker-registry ghcr-pull \
#         --docker-server=ghcr.io --docker-username=fireappleblack \
#         --docker-password=$CR_PAT
#     trace-k8s.yaml references it via imagePullSecrets.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

REGISTRY="ghcr.io"
OWNER="fireappleblack"
IMAGE="$REGISTRY/$OWNER/trace"
NAMESPACE="trace"

VER="${1:-}"
if [[ -z "$VER" ]]; then
  echo "usage: $0 <version>     e.g. $0 v0.4.0" >&2
  exit 1
fi

# Soft preflight: warn (don't block) if we're not logged in to GHCR — the push
# would otherwise fail with a less obvious error.
if ! podman login --get-login "$REGISTRY" >/dev/null 2>&1; then
  echo ">> note: not logged in to $REGISTRY. Run:" >&2
  echo "     echo \$CR_PAT | podman login $REGISTRY -u $OWNER --password-stdin" >&2
fi

# Project root = two levels up from this script (deploy/ -> trace-server/ -> root)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
echo ">> project root: $ROOT"

echo ">> building $IMAGE:$VER (arm64 — matches the Ampere nodes)"
podman build -f trace-server/Containerfile -t "$IMAGE:$VER" .

echo ">> pushing $IMAGE:$VER to GHCR"
podman push "$IMAGE:$VER"

echo ">> rolling Deployment to $IMAGE:$VER"
kubectl -n "$NAMESPACE" set image deploy/trace trace="$IMAGE:$VER"
kubectl -n "$NAMESPACE" rollout status deploy/trace --timeout=120s

echo ">> live pods:"
kubectl -n "$NAMESPACE" get pods -o wide -l app=trace
echo ">> done — trace is now running $VER"
