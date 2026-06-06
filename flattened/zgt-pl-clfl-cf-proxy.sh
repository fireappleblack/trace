#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# cf-proxy.sh — flip the Cloudflare proxy ON or OFF for the sites in
# proxied-hosts.conf. This is the data-plane half of the outage bypass:
# "off" grey-clouds the hostnames so visitors hit the origin directly,
# routing AROUND a broken Cloudflare edge (the Nov-18-2025 failure mode).
#
#   CF_API_TOKEN=...  ./cf-proxy.sh off [zone]     # bypass  (proxy → DNS-only)
#   CF_API_TOKEN=...  ./cf-proxy.sh on  [zone]     # restore (DNS-only → proxy)
#
# With no [zone], acts on every zone listed in proxied-hosts.conf. With a zone,
# acts only on that zone's hosts. Idempotent.
#
# Token: a Cloudflare API token with Zone:DNS:Edit + Zone:Zone:Read for the
# zones. Keep it OUT of git — pass via the CF_API_TOKEN env var (e.g. from a
# password manager). Deps: curl, jq.
#
# IMPORTANT: "off" only helps if the origin can serve direct — i.e. the origin
# firewall is OPEN (origin-firewall.sh open / OCI security list) and the origin
# holds a browser-trusted cert (DNS-01 LE, not Cloudflare Origin CA). See
# FALLBACK.md for the full runbook ordering.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

MODE="${1:-}"; ONLY_ZONE="${2:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="$HERE/proxied-hosts.conf"
API="https://api.cloudflare.com/client/v4"

case "$MODE" in on) PROXIED=true ;; off) PROXIED=false ;; *)
  echo "usage: CF_API_TOKEN=... $0 <on|off> [zone]" >&2; exit 1 ;; esac
: "${CF_API_TOKEN:?set CF_API_TOKEN (Cloudflare API token, never commit it)}"
command -v jq >/dev/null || { echo "needs jq" >&2; exit 1; }

cf() { curl -fsS -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json" "$@"; }

declare -A ZONE_ID
zone_id() {
  local z="$1"
  if [[ -z "${ZONE_ID[$z]:-}" ]]; then
    ZONE_ID[$z]="$(cf "$API/zones?name=$z" | jq -r '.result[0].id // empty')"
    [[ -n "${ZONE_ID[$z]}" ]] || { echo "zone not found in Cloudflare: $z" >&2; exit 1; }
  fi
  printf '%s' "${ZONE_ID[$z]}"
}

echo ">> Setting proxied=$PROXIED for hosts in $CONF ${ONLY_ZONE:+(zone: $ONLY_ZONE)}"
while read -r zone host _; do
  [[ -z "${zone:-}" || "$zone" == \#* ]] && continue
  [[ -n "$ONLY_ZONE" && "$zone" != "$ONLY_ZONE" ]] && continue
  zid="$(zone_id "$zone")"
  # Only A/AAAA/CNAME records can be proxied; match the exact hostname.
  recs="$(cf "$API/zones/$zid/dns_records?name=$host&type=A,AAAA,CNAME")"
  n="$(jq '.result | length' <<<"$recs")"
  if [[ "$n" -eq 0 ]]; then echo "   !! no proxiable record for $host (skipping)"; continue; fi
  for rid in $(jq -r '.result[].id' <<<"$recs"); do
    cf -X PATCH "$API/zones/$zid/dns_records/$rid" \
       --data "{\"proxied\":$PROXIED}" >/dev/null
    echo "   $host  → proxied=$PROXIED"
  done
done < "$CONF"

echo ">> Done. ${PROXIED:+}"
[[ "$PROXIED" == "false" ]] && cat <<'NOTE'
   Bypass active. Remember the other two legs (FALLBACK.md):
     • origin firewall must be OPEN  (./origin-firewall.sh open  on each node, + OCI security list)
     • verify: curl -sI https://<host>/  → 200 from origin, trusted cert
   To restore once Cloudflare is healthy:  ./cf-proxy.sh on
NOTE
exit 0
