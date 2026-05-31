#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# One-command build + push + rollout for the trace app, with versioned tags.
#
#   ./trace-server/deploy/deploy.sh v3
#
# Each call builds a uniquely-tagged image, pushes it to the in-cluster
# registry, and rolls the Deployment to it. Unique tags mean Kubernetes always
# sees a real change and does a clean rollout — no scale-to-zero, no stale-pod
# guessing, no "is this :latest the new one?".
#
# Run it from anywhere; it locates the project root relative to itself.
# Requires: podman (Mac), kubectl (pointed at the cluster), and the registry
# reachable at $REGISTRY (port 30500 open to your Mac — see README).
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

REGISTRY="redland001.hsabren.co.uk:30500"
IMAGE="$REGISTRY/trace"
NAMESPACE="trace"

VER="${1:-}"
if [[ -z "$VER" ]]; then
  echo "usage: $0 <version>     e.g. $0 v3" >&2
  exit 1
fi

# Project root = two levels up from this script (deploy/ -> trace-server/ -> root)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
echo ">> project root: $ROOT"

echo ">> building $IMAGE:$VER (arm64)"
podman build -f trace-server/Containerfile -t "$IMAGE:$VER" .

echo ">> pushing $IMAGE:$VER"
# --tls-verify=false: the registry is plain HTTP on a trusted network.
podman push --tls-verify=false "$IMAGE:$VER"

echo ">> rolling Deployment to $IMAGE:$VER"
kubectl -n "$NAMESPACE" set image deploy/trace trace="$IMAGE:$VER"
kubectl -n "$NAMESPACE" rollout status deploy/trace --timeout=120s

echo ">> live pods:"
kubectl -n "$NAMESPACE" get pods -o wide -l app=trace
echo ">> done — trace is now running $VER"
