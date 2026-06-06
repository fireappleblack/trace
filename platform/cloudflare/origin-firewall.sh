#!/usr/bin/env bash
# flatten:begin
# repo-path: platform/cloudflare/origin-firewall.sh
# generated: 2026-06-06T16:30:04Z by flatten.py — do not edit this block
# flatten:end

# ─────────────────────────────────────────────────────────────────────────
# origin-firewall.sh — host firewalld layer for the Cloudflare origin lockdown.
# Run ON EACH NODE (redland001 AND yellowland001), as root.
#
#   sudo ./origin-firewall.sh lock     # 80/443 ← Cloudflare IP ranges only
#   sudo ./origin-firewall.sh open     # 80/443 ← anyone (emergency bypass)
#   sudo ./origin-firewall.sh status
#
# ── READ THIS FIRST — which layer actually enforces ──
# There are TWO layers (DEPLOYMENT.md §7): the OCI security list (at the VCN,
# UPSTREAM of the host) and host firewalld. The OCI security list is the
# AUTHORITATIVE, reliable enforcement point and sits outside k3s's iptables —
# do the real lockdown THERE (replace the 0.0.0.0/0 rules on 80/443 with one
# rule per Cloudflare range; this script prints that list with `ranges`).
# This firewalld layer is DEFENSE-IN-DEPTH. With k3s/klipper managing iptables,
# host firewalld rich rules may or may not intercept ingress depending on chain
# order — so after `lock`, VERIFY from a non-Cloudflare IP that 443 is refused.
# If it isn't, rely on the OCI security list and treat firewalld as belt only.
#
# Cloudflare publishes its ranges at cloudflare.com/ips-v4 and /ips-v6; this
# script fetches them live so the set stays current.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail
CMD="${1:-status}"
ZONE="public"                    # adjust if your nodes use a different firewalld zone
PORTS=(80 443)

need_root() { [[ $EUID -eq 0 ]] || { echo "run as root (sudo)" >&2; exit 1; }; }
cf_ranges() { curl -fsS https://www.cloudflare.com/ips-v4; echo; curl -fsS https://www.cloudflare.com/ips-v6; echo; }

case "$CMD" in
  ranges)
    cf_ranges
    ;;
  lock)
    need_root
    command -v firewall-cmd >/dev/null || { echo "firewalld not present" >&2; exit 1; }
    echo ">> Locking ${PORTS[*]} to Cloudflare ranges (firewalld zone: $ZONE)"
    # Remove any blanket port-open so the rich rules are the only path in.
    for p in "${PORTS[@]}"; do firewall-cmd --permanent --zone="$ZONE" --remove-port="${p}/tcp" 2>/dev/null || true; done
    # Clear our previously-added CF rich rules (idempotent re-lock).
    firewall-cmd --permanent --zone="$ZONE" --list-rich-rules | grep -F 'comment="cf-origin"' \
      | while read -r r; do firewall-cmd --permanent --zone="$ZONE" --remove-rich-rule="$r" || true; done
    while read -r cidr; do
      [[ -z "$cidr" ]] && continue
      fam=ipv4; [[ "$cidr" == *:* ]] && fam=ipv6
      for p in "${PORTS[@]}"; do
        firewall-cmd --permanent --zone="$ZONE" \
          --add-rich-rule="rule family=\"$fam\" source address=\"$cidr\" port port=\"$p\" protocol=\"tcp\" accept comment=\"cf-origin\""
      done
    done < <(cf_ranges)
    firewall-cmd --reload
    echo ">> Locked. VERIFY from a non-Cloudflare host: 443 must be refused/timed-out."
    echo "   Then do the same at the OCI security list (authoritative) — see ./origin-firewall.sh ranges."
    ;;
  open)
    need_root
    echo ">> EMERGENCY OPEN: ${PORTS[*]} to the world (bypass window)"
    firewall-cmd --permanent --zone="$ZONE" --list-rich-rules | grep -F 'comment="cf-origin"' \
      | while read -r r; do firewall-cmd --permanent --zone="$ZONE" --remove-rich-rule="$r" || true; done
    for p in "${PORTS[@]}"; do firewall-cmd --permanent --zone="$ZONE" --add-port="${p}/tcp"; done
    firewall-cmd --reload
    echo ">> Open. Don't forget the OCI security list must also allow 0.0.0.0/0 on 80/443 for the bypass."
    echo "   RE-LOCK both layers once Cloudflare is healthy."
    ;;
  status)
    command -v firewall-cmd >/dev/null && firewall-cmd --zone="$ZONE" --list-all || echo "firewalld not present"
    ;;
  *) echo "usage: sudo $0 <lock|open|status|ranges>" >&2; exit 1 ;;
esac
