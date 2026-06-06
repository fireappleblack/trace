# Cloudflare outage — fallback plan (platform)

How to stay up, calmly and fast, when Cloudflare itself fails — as on
**2025-11-18**, when an oversized bot-management config crashed Cloudflare's
core proxy globally for ~5.5h and every proxied site returned 5xx while the
origins were perfectly healthy. The fix that worked for site owners that day was
to **take Cloudflare out of the path** and serve direct.

> Keep this runbook where it's reachable **without** Cloudflare (this repo /
> local clone). Don't host your status page or these docs behind Cloudflare.

## The core idea

If Cloudflare's edge is broken but its DNS + API still work (the most common and
the Nov-18 case), you **grey-cloud** the proxied records so visitors hit the
origin directly. Three legs must all be true for that to actually serve:

1. **DNS flips** — `cf-proxy.sh off` sets the hostnames to DNS-only.
2. **Origin is reachable** — the CF-only firewall lockdown must be **opened**,
   or direct visitors are blocked (the lockdown that protects you normally is
   the thing that stops the bypass).
3. **Origin cert is trusted** — browsers hit the real hostnames directly, so the
   origin needs a browser-trusted LE cert (which the DNS-01 setup gives us; an
   Origin CA cert would throw warnings).

The deliberate trade: while bypassed you've removed the edge security layer and
are directly exposed. That's why the origin hardening exists (updated apps,
read-only WP core, egress limits, the thin origin rate-limits) — it's your cover
for those hours.

## Prepared in advance (do now, while calm)

- [ ] **DNS-01 + trusted origin cert** in place (README pattern) — leg 3.
- [ ] **`CF_API_TOKEN`** stored offline (password manager), with Zone:DNS:Edit —
      so `cf-proxy.sh` works even if the Cloudflare **dashboard** is the casualty
      (it has been: the Sept-2025 incident took out the dashboard/API while the
      data plane ran). Keep both the script path and the manual dashboard steps.
- [ ] **Low TTLs** on the proxied records (Cloudflare serves proxied records at
      a low TTL already; the grey-cloud A record uses `ttl:1` = auto/low) so the
      flip propagates fast.
- [ ] **`proxied-hosts.conf` current** — every proxied site listed, node SSH
      hostnames NOT listed.
- [ ] **Backup authoritative DNS** at a second provider holding a current export
      of each zone, for the rare total-Cloudflare-DNS failure (slow path —
      registrar NS changes take hours).
- [ ] **External monitoring NOT routed through Cloudflare** that checks each
      public hostname AND the origin IP directly, so you can tell "origin down"
      from "Cloudflare down" instantly.
- [ ] **Decide per site whether you'd even bypass.** A ~5h outage on the
      low-stakes `zip.*` sites is fine to just wait out; reserve the bypass for
      the site that actually matters. Don't rewire DNS under pressure for sites
      that don't need it.

## Incident runbook

**Detect / confirm it's Cloudflare:** public hostname returns 5xx **and** a
direct-to-origin check (origin IP + Host header) returns 200 → it's the edge,
not you. Check Cloudflare's status page for scope.

### Scenario A — edge 5xx, Cloudflare DNS + API up  (the Nov-18 case; most likely)
1. Open the origin: `sudo ./origin-firewall.sh open` on **both** nodes, **and**
   set the OCI security list 80/443 back to `0.0.0.0/0` (console is fastest
   under pressure).
2. Grey-cloud: `CF_API_TOKEN=... ./cf-proxy.sh off` (all sites) or
   `... ./cf-proxy.sh off <zone>` for just the one that matters.
3. Verify: `curl -sI https://<host>/` → 200 from origin with a trusted cert.
4. Post a status note (off-Cloudflare channel).
5. When Cloudflare is healthy ~30 min: `./cf-proxy.sh on`, then **re-lock** both
   firewall layers (`origin-firewall.sh lock` + OCI ranges). Don't skip the
   re-lock — that's the exposure window closing.

### Scenario B — Cloudflare dashboard down, API/data plane up  (Sept-2025 shape)
Same as A, but you can't use the dashboard — the `cf-proxy.sh` API path is your
only lever. (This is why the token lives offline.)

### Scenario C — Cloudflare authoritative DNS down  (rare, catastrophic)
`cf-proxy.sh` can't help (the API/DNS are gone). Switch registrar nameservers to
the backup DNS provider holding the current zone export, open the origin, serve
direct. Accept TLD NS propagation lag (hours). This is the slow last resort.

## Restore checklist
- [ ] Cloudflare status green and stable for ~30 min.
- [ ] `./cf-proxy.sh on` (records back to proxied).
- [ ] `sudo ./origin-firewall.sh lock` on both nodes + OCI security list back to
      CF ranges only.
- [ ] Verify 443 from a non-CF IP is refused again (exposure window closed).
- [ ] Note the incident + duration for your records.

## Tested vs assumed
The scripts are `bash -n` clean but unproven against live Cloudflare/cluster.
**Rehearse once, off-peak:** run `cf-proxy.sh off` + open the firewall for one
low-stakes zip host, confirm it serves direct with a trusted cert, then restore.
A bypass you've never rehearsed is a guess — same discipline as the DB restore.
