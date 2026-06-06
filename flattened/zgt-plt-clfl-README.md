<!-- flatten:begin
     repo-path: platform/cloudflare/README.md
     generated: 2026-06-06T16:30:04Z by flatten.py — do not edit this block
flatten:end -->

# Cloudflare edge — reusable pattern (platform)

Put any public site on the cluster behind Cloudflare for CDN, DDoS protection,
edge WAF, and bot mitigation, with the origin locked down and an outage bypass
ready. Backend-agnostic: the zip game (Flask) and WordPress (LEMP) use the same
pattern; only a little per-app edge tuning differs.

Plan: **Free to start, Pro ($20/mo annual) per zone only where the managed WAF
earns it** (e.g. the busy, attacked site). Pricing is per *zone* (registered
domain), not per subdomain.

## Architecture

```
visitor ── HTTPS ──► Cloudflare edge ── HTTPS (Full-Strict) ──► OCI node :443 ──► Traefik ──► Service/Pod
                     (CDN, WAF, DDoS,                          (origin firewall
                      bot, edge TLS)                            allows CF IPs only)
```

- **Edge TLS** is Cloudflare's free auto-managed cert (public-facing).
- **Origin TLS** stays a browser-**trusted Let's Encrypt cert** (via DNS-01),
  so SSL mode **Full (Strict)** validates it AND an emergency bypass serves a
  trusted cert. We do **not** use a Cloudflare Origin CA cert (browsers don't
  trust it → bypass would warn).
- **Origin lockdown:** ports 80/443 accept only Cloudflare's IP ranges, so
  attackers can't skip the edge by hitting the node IP. Enforced at the **OCI
  security list** (authoritative) + host `firewalld` (defense-in-depth).

## Three levels of this pattern

It helps to see what's done once vs per-domain vs per-site.

**Cluster-level (once):**
1. Switch cert-manager to **DNS-01** via Cloudflare — `cloudflare-dns01-issuer.yaml`.
   This is the keystone: locking port 80 breaks HTTP-01, so issuance must not
   depend on an inbound port. It also retires the port-80-redirect and
   delete-secret-to-reissue footguns (DEPLOYMENT.md §7).
2. **Lock the origin** to Cloudflare IPs on 80/443 — OCI security list (replace
   the `0.0.0.0/0` 80/443 rules with one per CF range; get the list from
   `./origin-firewall.sh ranges`) + `sudo ./origin-firewall.sh lock` on **both**
   nodes. Verify from a non-CF host that 443 is refused.

**Per-zone (once per registered domain):** add the domain as a Cloudflare zone
and point its registrar nameservers at Cloudflare. (Manual — the scripts don't
create zones or move nameservers.)

**Per-site (per hostname):**
1. `CF_API_TOKEN=... ./cf-onboard.sh <hostname> [ip1] [ip2]` — proxied A
   record(s) + Full-Strict/Always-HTTPS/min-TLS-1.2.
2. Point the site's Ingress at `letsencrypt-dns01-staging`, `cmctl renew`,
   confirm, flip to `letsencrypt-dns01-prod`, `cmctl renew` (never delete the
   secret).
3. App-specific edge tuning (below) + Bot Fight Mode.
4. Add the hostname to `proxied-hosts.conf` so the outage bypass covers it.

## Per-app edge tuning (the only part that differs)

- **WordPress (busy/attacked site → Pro):** enable the WordPress managed WAF
  ruleset; rate-limit `/wp-login.php` and `/xmlrpc.php` (or block xmlrpc);
  Super Bot Fight Mode. This is where Pro earns its $20.
- **zip game (Flask) and similar:** lighter touch on Free — Bot Fight Mode, the
  generic managed ruleset, and a rate-limit only on any abuse-prone API endpoint
  (e.g. a score/submit route). It's a low-sensitivity app; don't over-tune.

## Applying it to the zip game (worked example)

Zones: `hsabren.co.uk`, `derangedimagination.com`, `saidtheape.com`.

> **Watch the `hsabren.co.uk` zone:** it also holds the node SSH hostnames
> `redland001.hsabren.co.uk` / `yellowland001.hsabren.co.uk`. Those must stay
> **DNS-only (grey-cloud)** — Cloudflare only proxies HTTP/S, and you need raw
> SSH to them. `proxied-hosts.conf` deliberately lists only `zip.*`, so the
> bypass never touches the node records.

```
# once: DNS-01 issuer + token
kubectl -n cert-manager create secret generic cloudflare-api-token --from-literal=api-token='<TOKEN>'
kubectl apply -f platform/cloudflare/cloudflare-dns01-issuer.yaml

# migrate the trace cert to DNS-01 (staging → prod), per host or shared as today
kubectl -n trace annotate ingress trace cert-manager.io/cluster-issuer=letsencrypt-dns01-staging --overwrite
cmctl renew trace-tls -n trace && kubectl -n trace get certificate -w
# confirm, then:
kubectl -n trace annotate ingress trace cert-manager.io/cluster-issuer=letsencrypt-dns01-prod --overwrite
cmctl renew trace-tls -n trace

# onboard each zip host
export CF_API_TOKEN=...      # never commit
./platform/cloudflare/cf-onboard.sh zip.hsabren.co.uk
./platform/cloudflare/cf-onboard.sh zip.derangedimagination.com
./platform/cloudflare/cf-onboard.sh zip.saidtheape.com

# once both layers are confirmed working through CF, lock the origin
sudo ./platform/cloudflare/origin-firewall.sh lock     # on EACH node
# + replace the 0.0.0.0/0 80/443 rules in the OCI security list with CF ranges
```

## Files

```
platform/cloudflare/
├── README.md                     # this pattern
├── FALLBACK.md                   # "what if Cloudflare fails" prep + runbook
├── cloudflare-dns01-issuer.yaml  # DNS-01 ClusterIssuers (staging+prod)
├── proxied-hosts.conf            # which hostnames are proxied (drives bypass)
├── cf-onboard.sh                 # per-host onboarding (records + TLS settings)
├── cf-proxy.sh                   # bypass/restore (proxy on/off) via CF API
└── origin-firewall.sh            # host firewalld lock/open (run on each node)
```

## Order of operations (important)

Onboard sites and confirm they serve **through** Cloudflare **before** locking
the origin. If you lock first, a misconfigured proxy record locks you out of
your own site. Sequence: DNS-01 issuer → onboard + verify each host through CF →
*then* lock the origin (firewalld + OCI). Reverse for teardown.

## Tested vs assumed

- **Validated here:** YAML parses; all scripts `bash -n` clean; the bypass/
  onboard logic is straightforward CF API (`curl`+`jq`).
- **NOT validated against live Cloudflare / the cluster** (no access here): the
  exact CF API responses, that DNS-01 issues for your zones with the token
  scope, and — most importantly — whether host `firewalld` rich rules actually
  intercept ingress given k3s/klipper's iptables. **Treat the OCI security list
  as the real lockdown and verify port 443 is refused from a non-Cloudflare IP
  after locking.** Onboard one host end-to-end and confirm a trusted cert both
  through CF and (test) grey-clouded before rolling to all sites.
