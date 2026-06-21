#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# Build → push → roll out biglabel (static nginx). Same flow as trace's
# deploy.sh, minus the DB. Run from the repo root.
#
#   ./biglabel/deploy/deploy.sh v0.1.0
#
# Prereqs (first deploy only):
#   • `podman login ghcr.io -u fireappleblack` (classic PAT, write:packages)
#   • the ghcr-pull secret in the biglabel namespace (private image):
#       kubectl create namespace biglabel
#       kubectl -n trace get secret ghcr-pull -o yaml \
#         | sed 's/namespace: trace/namespace: biglabel/' | kubectl -n biglabel apply -f -
#     (or make the GHCR package public and drop imagePullSecrets from the manifest)
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

VERSION="${1:?usage: deploy.sh <version>, e.g. v0.1.0}"
IMAGE="ghcr.io/fireappleblack/biglabel:${VERSION}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # the biglabel/ dir

echo ">> building $IMAGE (arm64)"
podman build -f "$HERE/Containerfile" -t "$IMAGE" "$HERE"

echo ">> pushing $IMAGE"
podman push "$IMAGE"

echo ">> applying manifest + rolling out"
# Pin the running image to this version (keeps the manifest's tag as the floor).
kubectl apply -f "$HERE/deploy/biglabel-k8s.yaml"
kubectl -n biglabel set image deploy/biglabel nginx="$IMAGE"
kubectl -n biglabel rollout status deploy/biglabel

cat <<EOF

>> biglabel $VERSION rolled out → https://biglabel.saidtheape.com
   First time only:
     • TLS: confirm staging issuance, then flip to prod (per DEPLOYMENT §5):
         kubectl -n biglabel get certificate,order,challenge
         kubectl -n biglabel annotate ingress biglabel \\
           cert-manager.io/cluster-issuer=letsencrypt-prod --overwrite
         cmctl renew biglabel-tls -n biglabel        # NEVER delete the secret
         kubectl -n biglabel get certificate -w
     • Cloudflare: add 'saidtheape.com biglabel.saidtheape.com' to
       platform/cloudflare/proxied-hosts.conf, then
         CF_API_TOKEN=... ./platform/cloudflare/cf-onboard.sh biglabel.saidtheape.com
       (and once cut over, switch the issuer to letsencrypt-dns01-prod).
EOF
