<!-- flatten:begin
     repo-path: Docs/RESPONSIBILITY.md
     generated: 2026-06-09T05:05:40Z by flatten.py — do not edit this block
flatten:end -->

# Responsibility & Ownership

**Last updated:** 2026-06-08

This repo is no longer "the zip game" — it's becoming "the cluster," with the
zip game, WordPress, a shared MariaDB, and a mail server as co-tenants of one
k3s platform. Work happens across **parallel chats/workstreams**, so this file
exists to answer one question cleanly: **who owns this file, and which
workstream should be editing it?** The goal is to stop two concurrent chats
clobbering each other's work.

> Companion docs: **`STATUS.md`** (state & risk), **`DEPLOYMENT.md`**
> (canonical deploy/operate process), **`DECISIONS.md`** (append-only rationale
> & history), and **`IDEAS.md`** (backlog / uncommitted ideas). This file is
> *ownership*; those are *state*, *process*, *why*, and *maybe-later*.

---

## 1. Workstreams

- **Zip-game development** — the application: client, server code, schema, and
  the manifests specific to running *that* app (its own Deployment, Ingress,
  and dedicated Postgres).
- **Infrastructure / platform** — the shared platform every tenant depends on:
  TLS issuers, ingress conventions, Longhorn/storage, security posture, the
  shared MariaDB, the mail server, WordPress site templates, and cross-cutting
  jobs like backups. Lives under `platform/` (and `wordpress/`).
- **Docs** — shared; either workstream may edit, with coordination (see §4).

---

## 2. Ownership (current layout)

| Path | Owner | Notes |
|------|-------|-------|
| `trace.html` | Zip-game dev | The single-file client |
| `trace-server/app.py`, `db.py`, `schema.sql`, `requirements.txt` | Zip-game dev | App + data layer |
| `trace-server/Containerfile`, `README.md` | Zip-game dev | App image + app docs |
| `trace-server/deploy/trace-k8s.yaml` | Zip-game dev | App Deployment/Service/Ingress |
| `trace-server/deploy/postgres.yaml` | Zip-game dev | The zip game's **dedicated** Postgres (app-specific, not shared) |
| `trace-server/deploy/apply-db.sh`, `.secrets.env.example`, `.gitignore-snippet` | Zip-game dev | App DB secret tooling (the out-of-band pattern itself is documented in `DEPLOYMENT.md`) |
| `trace-server/deploy/deploy.sh` | Zip-game dev | App build/push/rollout — publishes versioned tags to GHCR (`ghcr.io/fireappleblack/trace`) |
| `platform/cluster-issuers.yaml` | **Infrastructure** | Shared TLS issuers — used by *every* tenant. Moved into `platform/` during the v0.3.0 directory split |
| `registry.yaml` | **Infrastructure** | Abandoned in-cluster registry — fully superseded by GHCR; safe to drop (keep only for reference) |
| `STATUS.md`, `DEPLOYMENT.md`, `RESPONSIBILITY.md`, `DECISIONS.md` | Shared | Coordinate edits (§4); `DECISIONS.md` is append-only (§4) |
| `IDEAS.md` | Zip-game dev | Backlog / parking-lot (uncommitted ideas) — distinct from `STATUS.md` (live) and `DECISIONS.md` (settled). Currently Trace-only; make it shared + tagged like `DECISIONS.md` if platform ideas start landing |
| `.gitignore`, `.dockerignore` | Shared | Coordinate edits |
| `platform/mariadb/` | **Infrastructure** | Shared MariaDB (StatefulSet, tuning, apply script) — a DB + least-priv user per WordPress tenant. *Authored 2026-06-08; not yet deployed.* |
| `platform/backups/` | **Infrastructure** | Cross-cutting off-cluster backups (`pg_dump` + `mariadb-dump` → Object Storage, Longhorn target, restore helper). *Authored; not yet deployed/restore-tested.* |
| `platform/cloudflare/` | **Infrastructure** | Cloudflare edge pattern: DNS-01 issuer, onboarding/bypass scripts, origin lockdown, outage fallback runbook. *Authored; not yet cut over.* |
| `wordpress/` | **Infrastructure** | WordPress (LEMP) per-site stack — `lemp-base.yaml`, `site-template.yaml`, `apply-site.sh`. *Authored; not yet deployed.* |
| *(future)* mail (Stalwart) | **Infrastructure** | Lands under `platform/mail/` (§3) |

**Rule of thumb:** if more than one tenant depends on it, it's
**Infrastructure**. If only the zip game uses it, it's **Zip-game dev** — even
if it's a database or an Ingress.

---

## 3. Directory layout (shared-infra split — begun in v0.3.0)

The split is well under way. `cluster-issuers.yaml`, the shared **MariaDB**,
**backups**, the **Cloudflare** edge, and the **WordPress (LEMP)** templates now
live under `platform/` and `wordpress/` (authored 2026-06-08; mail is still to
come). The layout is **additive** — **no further file moves are required**, only
additions.

```
/
├── trace.html                      # APP
├── trace-server/                   # APP (zip-game dev)
│   ├── app.py db.py schema.sql requirements.txt Containerfile README.md
│   └── deploy/
│       ├── trace-k8s.yaml postgres.yaml
│       └── apply-db.sh .secrets.env.example .gitignore-snippet deploy.sh
├── platform/                       # SHARED INFRA (infrastructure)
│   ├── cluster-issuers.yaml        # moved here in the v0.3.0 split
│   ├── mariadb/                    # shared MariaDB (authored 2026-06-08)
│   ├── backups/                    # off-cluster pg_dump/mariadb-dump + Longhorn (authored)
│   ├── cloudflare/                 # edge: DNS-01 issuer, onboarding/bypass, FALLBACK (authored)
│   ├── mail/                       # Stalwart (future)
│   └── ingress/                    # conventions, middleware e.g. HTTP->HTTPS redirect (future)
├── wordpress/                      # SHARED INFRA (infrastructure)
│   ├── lemp-base.yaml              # shared Nginx vhost + PHP-FPM pool (authored)
│   ├── site-template.yaml          # per-site templated manifest (authored)
│   └── apply-site.sh               # provision DB+user, render & apply (authored)
└── Docs/                           # shared docs: STATUS DEPLOYMENT RESPONSIBILITY DECISIONS IDEAS
```

---

## 4. Coordination rules

- **Append-only logs (`DECISIONS.md`) are the exception to "one editor".**
  Any chat may add its own dated, tagged entry; never edit or reformat
  another's. A decision that supersedes an earlier one adds a *new* entry
  referencing it, rather than rewriting the old. This makes the rule below
  specifically about *rewrites*.
- **Never have two chats editing the same file in the same session.** The
  shared docs (`STATUS.md`, `DEPLOYMENT.md`, this file) are the likeliest
  collision points — agree who's touching them before starting.
- **App vs platform manifests don't overlap**, so the two workstreams can run
  in parallel safely as long as each stays in its lane per §2.
- **The dedicated Postgres stays app-owned; the shared MariaDB is infra-owned.**
  Don't merge them — different tenants, different lifecycles, different owners.
- **Secrets are never committed** (only `.example` files are). Any new secret
  follows the out-of-band pattern in `DEPLOYMENT.md`.
- When ownership of a file is unclear, default to **Infrastructure** if any
  non-zip-game tenant might come to depend on it.

---

*Maintenance: update this file whenever a new tenant or shared component is
added, or when files move between workstreams. `STATUS.md` and `DEPLOYMENT.md`
reference it for ownership questions.*
