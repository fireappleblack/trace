<!-- flatten:begin
     repo-path: Docs/STATUS.md
     generated: 2026-06-06T16:14:29Z by flatten.py — do not edit this block
flatten:end -->

# Trace — Status & Resilience Review

**Checkpoint: 2026-06-03** (updated from 2026-05-31; zip-game + deploy changes folded in)

A snapshot of where the project stands, what's already resilient, where it
can fail, and which fixes are worth making before they hit diminishing
returns.

> **Process vs. state:** this document is the *state / risk* review. For *how to
> deploy and operate* the stack, see **`DEPLOYMENT.md`** (the canonical
> process doc). Keep the split clean — risk and status here, procedure there.

**Changed since the last checkpoint:**
- **Zip-game & deploy (2026-06-03):** GHCR migration completed — image published
  to `ghcr.io/fireappleblack/trace`, pulled via the `ghcr-pull` imagePullSecret,
  with `deploy.sh` building/pushing/rolling versioned tags; side-loading and the
  self-hosted registry retired. Added cheat mode (flagged, excluded from public
  boards), wiggliness as a first-class `w` URL parameter with a main-UI slider,
  and an onboarding **placeholder backdrop** (the board no longer shows the real
  puzzle pre-consent — a sample/last-solve is shown instead). The server's
  additive ADD COLUMN migration now includes `cheated`, so it self-applies on
  deploy. ⚠️ **TLS regressed this session** (see §1): the edge is back on
  Traefik's default self-signed cert and Let's Encrypt **production** is
  rate-limited until 2026-06-05 00:58 UTC.
- **App (2026-05-31):** TLS brought up across three domains on one cert; the DB
  password moved out of git (gitignored secrets file + `apply-db.sh`); all
  player-facing copy moved into the database with a new staged onboarding flow.
- **Infrastructure (2026-05-31):** Traefik + servicelb re-enabled (both had been
  disabled at the k3s level); Postgres confirmed running on **Longhorn**
  (replicas-2), with Longhorn set as the **sole default** StorageClass;
  cert-manager installed; trusted production certs issued on all three domains
  (later regressed — see the 2026-06-03 note); stale RustDesk ports closed; the
  k8s API (6443) confirmed restricted to the private subnet.

---

## 1. Where things stand

**Application**
- `trace.html` — single-file client: puzzle generator/solver, hints, retrace
  input, an optional cheat mode (solutions shown; attempts flagged and kept off
  public leaderboards), adjustable path "wiggliness" (`w` URL parameter / main-UI
  slider), consent gate, local SQLite-in-browser persistence, optional server
  sync. Served by the Flask app (one canonical copy, no duplication).
- **Onboarding flow:** the real puzzle is generated up front but hidden; on load
  the player sees a **sample backdrop** (a finished example, or their last solve)
  so the puzzle can't be studied before the timer. The first tap reveals a small
  welcome banner (phrase chosen at random client-side); its **OK** opens the
  data-protection options card; consent saved → the real puzzle is revealed and
  gameplay enabled. The board is locked through all three stages.
- **Editable UI text in the database:** the `ui_text` table holds every
  player-facing string that may change for legal/design reasons — the welcome
  banner phrases, the consent-card copy, the ToS body, and the FAQ. One query
  (`/api/ui-text`) returns it all; the client carries the same text as an
  offline fallback. Seeded only when empty, so direct edits are never
  overwritten. Editing is currently by direct SQL; an admin UI is still to be
  built (see §6).
- Flask + gunicorn server (`app.py`, `db.py`, `schema.sql`): serves the
  client and a REST API for users, attempts, leaderboards, aggregates, the
  insights slicer, and UI text. Two gunicorn workers per pod. The server does
  no game logic — the browser generates, solves, and times puzzles; the server
  only records results and computes stats over them.
- Database layer supports SQLite (local dev) and Postgres (deployed), chosen
  from env. Connection manager with a per-process pool, startup retry, and
  live-connection recovery.

**Infrastructure**
- 2-node k3s on Oracle Cloud ARM (Ampere A1, ARM64, Oracle Linux 10):
  - `redland001` — control-plane — private `10.0.0.193`, public (edge-NAT)
    `141.147.107.161`, AD-1.
  - `yellowland001` — worker — private `10.0.0.187`, AD-3.
  - Nodes hold **only private IPs**; public reachability is Oracle **edge NAT**.
    The two nodes sit in different availability/fault domains.
- **Ingress:** Traefik (k3s bundled) + klipper `servicelb`, both re-enabled this
  session. Host 80/443 are bound on **both** nodes, so either can serve.
- **Storage:** Longhorn is the **sole default** StorageClass,
  `numberOfReplicas: 2` — volumes are replicated across both nodes. `local-path`
  is retained but **non-default**, for caches/scratch only.
  ⚠️ k3s re-marks `local-path` as default on upgrade — re-patch after upgrades,
  and **always set `storageClassName: longhorn` explicitly** on every PVC.
- Postgres: dedicated StatefulSet, 1 replica, **`longhorn` PVC (replicas-2,
  healthy)**. The app builds the connection from discrete params (no URL
  password-escaping footgun). Credentials are in a k8s Secret created
  **out-of-band** from a gitignored `.secrets.env` via `apply-db.sh` — no secret
  is in any committed manifest.
- App: Deployment, 2 replicas, rolling updates, stateless against Postgres.
- Images: published to **GHCR** (`ghcr.io/fireappleblack/trace`), pulled via the
  `ghcr-pull` imagePullSecret; `deploy.sh` builds/pushes/rolls versioned tags.
  Side-loading and the self-hosted registry are retired.
- TLS: cert-manager (v1.20.1) + Traefik + Let's Encrypt (HTTP-01), covering
  **three** hostnames on one SAN cert — `zip.hsabren.co.uk`,
  `zip.derangedimagination.com`, `zip.saidtheape.com`. ⚠️ **Currently regressed
  (2026-06-03):** the edge is serving Traefik's default self-signed cert; Let's
  Encrypt **production** is rate-limited (duplicate-certificate limit, 5 per
  exact SAN set per 168h) until **2026-06-05 00:58 UTC**. The HTTP-01 path is
  proven (5 prior issuances), so recovery is: validate on **staging** now, then
  flip to prod **once** after the window clears. Auto-renewal resumes once a
  trusted cert is re-issued. *(TLS issuers are Infrastructure-owned — platform
  workstream.)*

---

## 2. What's already resilient (built and tested)

- **App survives Postgres restarting underneath it** — the pool validates
  connections on borrow and recycles dead ones; verified by restarting PG
  under a live app and seeing it recover on the next request.
- **App tolerates Postgres not being ready at startup** — connect-retry loop
  plus an init container that waits on `pg_isready`; verified.
- **Postgres data survives a node loss** — the `longhorn` PVC is replicated
  across both nodes (replicas-2, confirmed healthy). If a node is lost or
  drained, Postgres reschedules onto the survivor with its replica intact — the
  data is no longer pinned to one node.
- **Stateless app, 2 replicas, rolling updates** — one pod (or node) can go
  without taking the service down, as long as Postgres is reachable.
- **Self-healing** — readiness/liveness probes on `/api/health` restart or
  drain unhealthy pods automatically.
- **TLS auto-renewal** — cert-manager renews Let's Encrypt certs without
  intervention. *(Paused until the prod cert is re-issued — see §1.)*

---

## 3. Failure points & resilience gaps

Ordered roughly by stakes.

### Data / persistence — **highest stakes**
- **No backups.** Longhorn replication protects against *hardware/node* loss,
  but **not** against a bad migration, logical corruption, or an accidental
  `delete pvc` / namespace deletion — any of which still loses all users,
  attempts, and leaderboards permanently. Off-cluster backups remain the single
  most important gap (see §4 #1).
- **Both Longhorn replicas live on the same two nodes.** Replication survives
  *one* node failing, but losing both nodes (or Longhorn-level data loss)
  still destroys the data. Only an off-cluster backup covers this.
- **Capacity comes from the node boot disks.** Longhorn carves its replicas
  from the 200 GB boot volumes; aggregate Longhorn usage across all volumes
  needs watching so a full disk doesn't take down a node. (`local-path`, used
  only for caches now, still enforces no quota.)

### Availability / single points of failure
- **Single Postgres instance** is the app's hard dependency. It now survives a
  node loss (reschedules via Longhorn), but during the restart/reschedule the
  app errors until PG returns — then it recovers automatically.
- **Single control-plane node.** If `redland001` dies, the cluster API is
  down — existing pods keep running on `yellowland001`, but nothing can be
  rescheduled or changed until it's back.
- **DNS points at one node.** All three hostnames → `redland001` only. If that
  node is down, the site is unreachable even though the worker can now also
  serve on 80/443. The three domains share one SAN cert, so they rise and fall
  together (and a DNS lapse on any one can stall renewal of the shared cert).
  A second A record → the worker is now genuinely useful (§4 #8).
- **Traefik** typically runs as a single replica in k3s; brief ingress outage
  if its node fails, until it reschedules.

### Security
- **SSH (22) is open to the world.** The k8s API (6443) and the other k3s
  ports are confirmed restricted to the `10.0.0.0/24` private subnet — good —
  but SSH still allows `0.0.0.0/0` and should be restricted to your source IP
  (§4 #3). (The stale RustDesk ports were closed this session.)
- **DB password is kept out of git** (gitignored `.secrets.env`, Secret created
  out-of-band by `apply-db.sh`; only `.secrets.env.example` is tracked).
  Residual exposure: it's plaintext in `.secrets.env` on the dev machine and
  base64 (not encrypted) in the cluster datastore — hence the secrets-encryption
  item below. **If the real password was ever committed before this change,
  rotate it** — scrubbing history doesn't reach existing clones/forks/backups.
- **GHCR pull credential is out of git too** — the `ghcr-pull` imagePullSecret
  (a classic PAT) is created imperatively, never committed; rotate by recreating
  it (and the local `$CR_PAT`) if exposed.
- **Secrets aren't encrypted at rest** by default in k3s — anyone with node or
  datastore access can read the Postgres password.
- **No app-level auth or rate limiting.** The API is anonymous and public;
  `/api/users` and `/api/attempts` could be spammed.

### Operational
- **Manual deploys** (build → push → rollout). Fine for one maintainer; no
  automated build or rollback.
- **No PodDisruptionBudget** — a node drain could evict both app replicas at
  once.
- **Additive-only schema migrations.** Adding columns is handled by an idempotent
  ADD COLUMN pass on startup (the `cheated` column landed this way); anything
  destructive or reshaping would be manual and risky.

### Observability
- **No monitoring or alerting.** A filled disk, a failed cert renewal, or a
  crash-looping pod is discovered only when something visibly breaks.

### Deliberate design choices (not bugs)
- **`/api/health` is shallow** (doesn't ping the DB). This is intentional: a
  deep check would pull *every* app pod out of rotation the instant PG blips,
  turning a brief DB hiccup into a full outage. The shallow check plus
  connection recovery keeps pods up and lets them reconnect — the better
  trade-off for this app.

---

## 4. Remediations worth doing (proportionate)

| # | Fix | Why | Effort |
|---|-----|-----|--------|
| 1 | **Off-cluster backups** — logical `pg_dump` (and `mysqldump` / mail export once those land) to Oracle Object Storage on a CronJob, plus a Longhorn backup target to the same bucket, with one tested restore | Longhorn covers node loss; this covers corruption, bad migrations, and accidental deletion — the worst remaining outcome | Low–med |
| 2 | ~~Keep the real DB password out of git~~ — **DONE**: gitignored `.secrets.env` + `apply-db.sh` create the Secret out-of-band. (Rotate the password if it was committed earlier.) | Prevents credential leak via the repo | — |
| 3 | **Restrict SSH (22)** to your own source IP in the Oracle security list (6443 + k3s ports already private-subnet-only; RustDesk ports already closed) | Closes the last world-open port | Low |
| 4 | **Enable k3s secrets encryption at rest** (`--secrets-encryption`) | Sensible on public cloud VMs | Low |
| 5 | **PodDisruptionBudget** (minAvailable: 1) for the app | Keeps a replica up during node maintenance | Low |
| 6 | **External uptime check** hitting `https://zip.hsabren.co.uk/api/health` | Cheapest possible "is it down?" signal | Low |
| 7 | **Watch disk usage** — both node boot disks and aggregate Longhorn volume usage | Avoids a full-disk outage going unnoticed | Near-zero |
| 8 | *(Optional)* second DNS A record → worker node | Real redundancy now that both nodes bind 80/443 | Low |

The clear priority is **#1**. Everything below it is good hygiene; #1 is the
difference between "annoying outage" and "everything is gone." Longhorn has
narrowed that gap (node loss is now survivable) but has **not** closed it.

---

## 5. Deliberately NOT doing (diminishing returns for this project)

- **HA Postgres** (replication / CloudNativePG operator) — large complexity for
  a hobby puzzle app; Longhorn now gives storage-level resilience and automated
  backups cover the rest of the realistic risk.
- **HA control plane** (3 k3s servers + embedded etcd) — sensible for
  production, overkill for two nodes you control.
- **Full observability stack** (Prometheus/Grafana/Loki) — an external uptime
  check gives 90% of the value for ~1% of the effort.
- **NetworkPolicies / service mesh** — negligible benefit at this scale.
- **CI/CD pipeline** — worthwhile only if deploy frequency rises; `deploy.sh`
  (now on GHCR) is enough for now.
- **Sealed Secrets / SOPS / Vault** — the gitignored-file + out-of-band Secret
  approach (now in place) is sufficient at this scale. SOPS+age or Sealed
  Secrets would be the upgrade if a GitOps/declarative workflow is wanted later.

---

## 6. Outstanding setup tasks (separate from resilience)

- **Re-issue TLS** (regressed 2026-06-03 — see §1): validate on staging now,
  then after the prod rate-limit clears (**2026-06-05 00:58 UTC**) flip the
  Ingress to `letsencrypt-prod` and delete `trace-tls` **once** to trigger a
  single trusted issuance. *(Was previously live with trusted prod certs.)*
- Add a safe **HTTP→HTTPS redirect** once the cert is stable again (a global
  redirect added earlier would have broken the ACME HTTP-01 challenge).
- ~~Complete the **GHCR migration**~~ — **DONE (2026-06-03):** image on
  `ghcr.io/fireappleblack/trace`, pulled via `ghcr-pull`; `deploy.sh` repointed
  to GHCR; side-loading and the self-hosted registry retired.
- Build an **admin backend** so welcome-banner phrases and consent-card copy in
  `ui_text` can be edited by an admin without DB write access or code changes
  (interim method is direct SQL). *(Reminder carried forward.)*
- **Restrict SSH (22)** to your source IP (also §4 #3).
- *(Optional, performance)* tune Postgres for the small footprint
  (`shared_buffers` 32–64 MB, `work_mem` 4 MB, `max_connections` 20–30) and keep
  the app's connection pool small — to be folded in alongside the shared-MariaDB
  build.
