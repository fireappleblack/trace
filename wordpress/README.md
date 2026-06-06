<!-- flatten:begin
     repo-path: wordpress/README.md
     generated: 2026-06-06T16:30:04Z by flatten.py — do not edit this block
flatten:end -->

# WordPress (platform) — LEMP

One **two-container pod per site** (Nginx + PHP-FPM), single replica each, all
backed by the **shared MariaDB** (`platform/mariadb`) with a database +
least-privilege user per site (`DECISIONS.md` 2026-05-31 [platform]). Stack is
**LEMP** — Linux, Nginx, MariaDB/MySQL, PHP-FPM. Suited to ~10–20 low-traffic
sites alongside the zip game and mail.

## Why LEMP (and how the pod is shaped)

The official `wordpress` image has no Nginx variant, so a faithful LEMP build is
two containers in one pod sharing the site's `/var/www/html` volume:

- **`wordpress:php8.3-fpm`** — PHP only. Its entrypoint populates the volume and
  writes `wp-config.php` from the DB env on first start, then runs php-fpm on
  `:9000`.
- **`nginx:1.27-alpine`** — serves static files directly and reverse-proxies
  `*.php` to FPM over `127.0.0.1:9000` (loopback, same pod).

They share the html PVC; Nginx mounts it read-only. The pod is **Ready only when
both** Nginx (`/healthz`) and FPM (`:9000`) are up, so the Service never routes
to a half-started pod.

The memory win over Apache+mod_php is at idle and scale: Nginx is a flat
~15 MB, and with `pm = ondemand` the FPM pool spins workers up per request and
lets them die after 10s idle — so a quiet site costs little more than the FPM
master. Static assets (most of a page's requests) never touch PHP.

## Layout

```
wordpress/
├── lemp-base.yaml      # namespace + shared Nginx vhost & FPM pool ConfigMaps (apply once)
├── site-template.yaml  # per-site PVC + 2-container Deployment + Service + Ingress
├── apply-site.sh       # provision DB+user, render & apply (applies base too)
└── README.md
```

The Nginx vhost and FPM pool are **shared across all sites** (in `lemp-base.yaml`)
— the vhost is host-agnostic (the Ingress routes by hostname), and the pool
profile is identical everywhere. `apply-site.sh` applies the base idempotently
before each site.

## Prerequisites

1. Shared MariaDB deployed: `./platform/mariadb/apply-mariadb.sh`
2. Backups extended to MariaDB: re-run `./platform/backups/apply-backups.sh`
   **before** putting real content into a site.
3. DNS for the site's hostname → a node public IP (cert-manager can't issue
   until it resolves), and ports 80/443 open.

## Add a site

```
./wordpress/apply-site.sh <site-slug> <hostname> [issuer] [fpm-image]

./wordpress/apply-site.sh blog blog.derangedimagination.com
./wordpress/apply-site.sh shop shop.saidtheape.com
```

Default image is `wordpress:php8.3-fpm`; pass `wordpress:6.7-php8.3-fpm` (or
`…-fpm-alpine`, lighter) to pin a version. The script generates the per-site DB
password on first run only (re-runs reuse it), creates the Secret out-of-band,
provisions a scoped DB+user, applies the base, and renders the site.

## The memory / connection math (the dial that matters)

`pm.max_children` (in `lemp-base.yaml`, default **5**) is the one knob that
bounds both **PHP worker memory** and **DB connections** per site:

- **DB connections:** keep `(number of sites × pm.max_children)` under MariaDB's
  `max_connections = 60`. At 5 children that's ~12 busy sites' worth of headroom;
  raise MariaDB's cap (and its memory limit) deliberately if you exceed it.
- **Memory:** `memory_limit = 128M` is *per request*; typical WP requests use
  far less. The FPM container limit is **384Mi** — comfortable for ondemand at 5
  children with typical requests, **not** for a pathological 5 × 128M. If a site
  is memory-heavy, **lower `pm.max_children`** (e.g. 3) rather than only raising
  the container limit. Per-site overrides: point a site at its own pool
  ConfigMap (not wired up yet — ask if you want it).

To change tuning: edit `lemp-base.yaml`, `kubectl apply -f`, then
`kubectl -n wordpress rollout restart deploy -l app=wordpress`.

## TLS (per site, staging → prod)

Sites start on `letsencrypt-staging`. `apply-site.sh` prints the exact prod-flip
commands — and they use **`cmctl renew`, not secret-deletion** (the footgun from
`DEPLOYMENT.md` §7). Per-site certs are single-host SAN sets with their own
5/168h budget, so a lockout on one site can't affect the others — but still touch
prod once per site, never loop.

## Lifecycle

| Task | Command |
|------|---------|
| Update a site's image | re-run `apply-site.sh` with a new `fpm-image`, or `kubectl -n wordpress set image deploy/wp-<site> wordpress=<image>` |
| Restart a site | `kubectl -n wordpress rollout restart deploy/wp-<site>` |
| Tail PHP / Nginx logs | `kubectl -n wordpress logs deploy/wp-<site> -c wordpress` (or `-c nginx`) |
| Remove a site | `kubectl -n wordpress delete deploy,svc,ingress,pvc,secret -l site=<site>` then drop the DB+user in MariaDB |

> **Removing a site deletes its PVC and DB content — back up first.**

## Generic (non-WordPress) PHP

This exact two-container pattern hosts any PHP-FPM app: swap the `wordpress:*-fpm`
image for `php:8.3-fpm` (+ your code on the volume or baked into an image), drop
the `WORDPRESS_DB_*` env, and point the Nginx `root` at your docroot. Not built
as a separate template yet — say the word and I'll add a `php-app-template.yaml`.

## Tested vs assumed

- **Validated:** YAML parses; the embedded Nginx vhost & FPM pool survive YAML
  intact (`$uri`, `fastcgi_pass`, pool directives); template renders with all
  tokens substituted; Deployment carries both `wordpress` and `nginx` containers;
  `bash -n` clean.
- **NOT validated on the live cluster** (no cluster access here): that
  `wordpress:php8.3-fpm`'s entrypoint populates the shared volume as expected,
  that Nginx (uid 101) reads FPM-written files via world bits, the FastCGI path,
  the probes, and TLS issuance. Apply one site, watch `rollout status`, complete
  the browser install, upload a >2M image to confirm the upload limits, and check
  the cert before treating the pattern as proven. If Nginx 403s on static files,
  it's a perms issue — confirm `fsGroup: 33` took and WP files are world-readable.
