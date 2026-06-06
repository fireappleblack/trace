#!/usr/bin/env bash
# flatten:begin
# repo-path: platform/cloudflare/cf-onboard.sh
# generated: 2026-06-06T16:30:04Z by flatten.py — do not edit this block
# flatten:end

# ─────────────────────────────────────────────────────────────────────────
# cf-onboard.sh — put one hostname behind Cloudflare with the standard, safe
# settings, so adding a new site is one command + a couple of dashboard clicks.
#
#   CF_API_TOKEN=...  ./cf-onboard.sh <hostname> [ip1] [ip2]
#
#   CF_API_TOKEN=...  ./cf-onboard.sh zip.derangedimagination.com
#   CF_API_TOKEN=...  ./cf-onboard.sh blog.saidtheape.com 141.147.107.161 132.145.23.20
#
# IPs default to the two node public IPs (both bind 80/443 via klipper, so
# listing both gives basic origin redundancy — note: free Cloudflare round-robins
# without health checks, so if a node dies you remove its record manually).
#
# Sets, idempotently:
#   • proxied A record(s)  hostname → node IP(s)   (orange-cloud)
#   • zone SSL mode        = Full (Strict)         (encrypts CF→origin, validates origin cert)
#   • Always Use HTTPS     = on
#   • Minimum TLS          = 1.2
#
# PREREQUISITE (per zone, one-time, manual): the registered domain must already
# be a zone in your Cloudflare account with its registrar nameservers pointed at
# Cloudflare. This script does NOT create the zone or change nameservers.
#
# AFTER running: see README.md for the per-app edge tuning (WordPress managed
# ruleset / rate-limits vs. the zip game's lighter touch) and Bot Fight Mode,
# which are left to the dashboard as they vary per site and per plan.
#
# Deps: curl, jq. Token: Zone:DNS:Edit + Zone:Zone:Read + Zone Settings:Edit.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

HOST="${1:-}"
IP1="${2:-141.147.107.161}"     # redland001
IP2="${3:-132.145.23.20}"       # yellowland001
API="https://api.cloudflare.com/client/v4"

[[ -n "$HOST" ]] || { echo "usage: CF_API_TOKEN=... $0 <hostname> [ip1] [ip2]" >&2; exit 1; }
: "${CF_API_TOKEN:?set CF_API_TOKEN}"
command -v jq >/dev/null || { echo "needs jq" >&2; exit 1; }

# Zone = the registered domain = the last two labels of the hostname. (Good for
# .com/.co/.io etc.; for multi-part public suffixes like .co.uk, see note below.)
# .co.uk handling: take the last THREE labels when the 2nd-to-last is a known
# 2-label TLD. Keep it simple and explicit for the suffixes you actually use.
case "$HOST" in
  *.co.uk|*.org.uk|*.gov.uk) ZONE="$(echo "$HOST" | awk -F. '{print $(NF-2)"."$(NF-1)"."$NF}')" ;;
  *)                          ZONE="$(echo "$HOST" | awk -F. '{print $(NF-1)"."$NF}')" ;;
esac
echo ">> hostname=$HOST  zone=$ZONE  origins=$IP1${IP2:+,$IP2}"

cf() { curl -fsS -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json" "$@"; }

ZID="$(cf "$API/zones?name=$ZONE" | jq -r '.result[0].id // empty')"
[[ -n "$ZID" ]] || { echo "zone '$ZONE' not in Cloudflare — add it & point nameservers first." >&2; exit 1; }

upsert_a() {
  local ip="$1" existing
  [[ -z "$ip" ]] && return 0
  existing="$(cf "$API/zones/$ZID/dns_records?type=A&name=$HOST&content=$ip" | jq -r '.result[0].id // empty')"
  if [[ -n "$existing" ]]; then
    cf -X PATCH "$API/zones/$ZID/dns_records/$existing" --data "{\"proxied\":true}" >/dev/null
    echo "   updated A $HOST → $ip (proxied)"
  else
    cf -X POST "$API/zones/$ZID/dns_records" \
       --data "{\"type\":\"A\",\"name\":\"$HOST\",\"content\":\"$ip\",\"proxied\":true,\"ttl\":1}" >/dev/null
    echo "   created A $HOST → $ip (proxied)"
  fi
}
upsert_a "$IP1"
upsert_a "$IP2"

set_zone() { # <setting> <json-value>
  cf -X PATCH "$API/zones/$ZID/settings/$1" --data "{\"value\":$2}" >/dev/null && echo "   set $1 = $2"
}
set_zone ssl '"strict"'
set_zone always_use_https '"on"'
set_zone min_tls_version '"1.2"'

cat <<EOF
>> $HOST is onboarded (proxied, Full-Strict TLS).
   Still to do by hand (vary per site / plan — see README.md):
     • DNS-01 cert: ensure the Ingress for $HOST uses letsencrypt-dns01-* and has issued.
     • Edge tuning: managed WAF ruleset + rate-limits (WordPress) or light touch (zip game).
     • Bot Fight Mode (dashboard → Security → Bots).
   Add $HOST to proxied-hosts.conf so the outage bypass covers it.
EOF
