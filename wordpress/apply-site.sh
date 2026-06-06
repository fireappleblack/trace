#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# apply-site.sh — stand up (or update) one WordPress site on the shared MariaDB
# ─────────────────────────────────────────────────────────────────────────
#   ./wordpress/apply-site.sh <site-slug> <hostname> [issuer] [wp-image]
#
#   ./wordpress/apply-site.sh blog blog.derangedimagination.com
#   ./wordpress/apply-site.sh shop shop.saidtheape.com letsencrypt-prod
#
# What it does:
#   1. Derives DB-safe names from the slug.
#   2. Generates a per-site DB password ON FIRST RUN only (reuses the existing
#      one on re-runs, so a re-apply never locks WordPress out of its DB).
#   3. Creates the per-site DB-password Secret out-of-band (never in git).
#   4. Provisions a DB + least-privilege user in the shared MariaDB (idempotent;
#      the user can touch ONLY this site's DB).
#   5. Renders site-template.yaml and applies it.
#
# Prereqs: the shared MariaDB is deployed (platform/mariadb), DNS for <hostname>
# resolves to a node public IP, and ports 80/443 are open (for ACME + serving).
#
# DNS pre-flight matters: cert-manager can't issue until <hostname> resolves.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS_WP=wordpress
NS_DB=mariadb
DB_ROOT_SECRET=mariadb-root           # key: MARIADB_ROOT_PASSWORD

SITE="${1:-}"; HOST="${2:-}"
ISSUER="${3:-letsencrypt-staging}"
WP_IMAGE="${4:-wordpress:php8.3-fpm}"      # LEMP: a *-fpm image (NOT -apache). Pin fuller for prod, e.g. wordpress:6.7-php8.3-fpm. -fpm-alpine is lighter.

if [[ -z "$SITE" || -z "$HOST" ]]; then
  echo "usage: $0 <site-slug> <hostname> [issuer] [wp-image]" >&2
  exit 1
fi
if [[ ! "$SITE" =~ ^[a-z0-9-]+$ ]]; then
  echo "site-slug must be [a-z0-9-] only (got: $SITE)" >&2
  exit 1
fi

# DB identifiers can't contain hyphens unquoted — map - → _. MySQL usernames
# max 32 chars, so keep slugs short.
DB_SAFE="${SITE//-/_}"
DB_NAME="wp_${DB_SAFE}"
DB_USER="wp_${DB_SAFE}"
if (( ${#DB_USER} > 32 )); then
  echo "Derived DB user '$DB_USER' exceeds MySQL's 32-char limit — use a shorter slug." >&2
  exit 1
fi

TMP="$(mktemp -d)"; chmod 700 "$TMP"
cleanup() { find "$TMP" -type f -exec shred -u {} + 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT

# ── 0. Read the MariaDB root password (single source of truth) ──
ROOT_PW="$(kubectl -n "$NS_DB" get secret "$DB_ROOT_SECRET" \
            -o jsonpath='{.data.MARIADB_ROOT_PASSWORD}' 2>/dev/null | base64 -d || true)"
if [[ -z "$ROOT_PW" ]]; then
  echo "ERROR: could not read MARIADB_ROOT_PASSWORD from $NS_DB/$DB_ROOT_SECRET." >&2
  echo "       Deploy the shared MariaDB first: ./platform/mariadb/apply-mariadb.sh" >&2
  exit 1
fi

# ── 1. Per-site DB password: reuse if the secret exists, else generate ──
kubectl create namespace "$NS_WP" --dry-run=client -o yaml | kubectl apply -f -
SITE_PW="$(kubectl -n "$NS_WP" get secret "wp-${SITE}-db" \
            -o jsonpath='{.data.WORDPRESS_DB_PASSWORD}' 2>/dev/null | base64 -d || true)"
if [[ -n "$SITE_PW" ]]; then
  echo ">> Reusing existing DB password for site '$SITE'."
else
  SITE_PW="$(openssl rand -hex 24)"   # alnum-only: safe in SQL, env, and shells
  echo ">> Generated a new DB password for site '$SITE'."
fi

# ── 2. Per-site DB-password Secret (verbatim via temp env-file) ──
PWFILE="$TMP/site.env"; : > "$PWFILE"; chmod 600 "$PWFILE"
printf 'WORDPRESS_DB_PASSWORD=%s\n' "$SITE_PW" >> "$PWFILE"
kubectl create secret generic "wp-${SITE}-db" \
  --namespace "$NS_WP" \
  --from-env-file="$PWFILE" \
  --dry-run=client -o yaml | kubectl apply -f -

# ── 3. Provision DB + least-privilege user (idempotent) ──
# SQL (incl. the site password) goes via STDIN, so it's never in any argv.
# The ROOT password is passed to the in-pod client; it is briefly visible in
# the MariaDB pod's process list during provisioning (single-maintainer,
# trusted node — acceptable; noted in README).
SQL="$TMP/provision.sql"; : > "$SQL"; chmod 600 "$SQL"
cat > "$SQL" <<EOF
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'%' IDENTIFIED BY '${SITE_PW}';
ALTER USER '${DB_USER}'@'%' IDENTIFIED BY '${SITE_PW}';
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'%';
FLUSH PRIVILEGES;
EOF

echo ">> Provisioning ${DB_NAME} / ${DB_USER} on the shared MariaDB..."
kubectl -n "$NS_DB" exec -i statefulset/mariadb -- \
  mariadb -uroot -p"$ROOT_PW" < "$SQL"

# ── 4. Render + apply the site manifest ──
# Ensure the shared LEMP base (namespace + Nginx vhost + FPM pool ConfigMaps)
# exists — idempotent, safe to re-apply on every site.
kubectl apply -f "$HERE/lemp-base.yaml"

RENDERED="$TMP/site.yaml"
sed -e "s|__SITE__|${SITE}|g" \
    -e "s|__HOST__|${HOST}|g" \
    -e "s|__DB_NAME__|${DB_NAME}|g" \
    -e "s|__DB_USER__|${DB_USER}|g" \
    -e "s|__WP_IMAGE__|${WP_IMAGE}|g" \
    -e "s|__ISSUER__|${ISSUER}|g" \
    "$HERE/site-template.yaml" > "$RENDERED"
kubectl apply -f "$RENDERED"
kubectl -n "$NS_WP" rollout status deploy/"wp-${SITE}"

cat <<EOF

>> Site '${SITE}' applied → https://${HOST}
   DB: ${DB_NAME}  user: ${DB_USER}  (rights scoped to that DB only)
   Issuer: ${ISSUER}

   TLS: confirm staging issuance, then flip THIS site to prod (per DEPLOYMENT.md §5/§7):
     kubectl -n ${NS_WP} get certificate,order,challenge
     kubectl -n ${NS_WP} annotate ingress wp-${SITE} \\
       cert-manager.io/cluster-issuer=letsencrypt-prod --overwrite
     cmctl renew wp-${SITE}-tls -n ${NS_WP}                # ONE controlled re-issue
     kubectl -n ${NS_WP} get certificate -w
   Do NOT 'delete secret wp-${SITE}-tls' to force issuance — on the prod issuer
   that can double-trigger and burn two of the 5-per-168h slots, and serves an
   untrusted cert in the gap (DEPLOYMENT.md §7). Per-site certs each have their
   OWN budget, so a lockout here is isolated — but still touch prod once.

   Then finish WordPress setup in the browser at https://${HOST}
EOF
