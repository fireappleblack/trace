# Trace — Status & Resilience Review

**Checkpoint: 2026-05-31** (updated from 2026-05-29)

A snapshot of where the project stands, what's already resilient, where it
can fail, and which fixes are worth making before they hit diminishing
returns.

**Changed since the last checkpoint:** TLS now covers three domains on one
cert; the DB password is out of git (gitignored secrets file + `apply-db.sh`);
all player-facing copy moved into the database with a new staged onboarding
flow (inert puzzle → random welcome banner → consent card).

---

## 1. Where things stand

**Application**
- `trace.html` — single-file client: puzzle generator/solver, hints, retrace
  input, consent gate, local SQLite-in-browser persistence, optional server
  sync. Served by the Flask app (one canonical copy, no duplication).
- **Onboarding flow:** on load the player sees the real puzzle, inert; the
  first tap reveals a small welcome banner (phrase chosen at random
  client-side); its **OK** opens the data-protection options card; consent
  saved → gameplay enabled. The board is locked through all three stages.
- **Editable UI text in the database:** the `ui_text` table holds every
  player-facing string that may change for legal/design reasons — the welcome
  banner phrases, the consent-card copy, the ToS body, and the FAQ. One query
  (`/api/ui-text`) returns it all; the client carries the same text as an
  offline fallback. Seeded only when empty, so direct edits are never
  overwritten. Editing is currently by direct SQL; an admin UI is still to be
  built (see §6).
- Flask + gunicorn server (`app.py`, `db.py`, `schema.sql`): serves the
  client and a REST API for users, attempts, leaderboards, aggregates, the
  insights slicer, and UI text. Two gunicorn workers per pod.
- Database layer supports SQLite (local dev) and Postgres (deployed), chosen
  from env. Connection manager with a per-process pool, startup retry, and
  live-connection recovery.

**Infrastructure**
- 2-node k3s on Oracle Cloud ARM (Ampere): `redland001` (control-plane),
  `yellowland001` (worker). Public IPs.
- Postgres: dedicated StatefulSet, 1 replica, `local-path` PVC. The app
  builds the connection from discrete params (no URL password-escaping
  footgun). Credentials are in a k8s Secret created **out-of-band** from a
  gitignored `.secrets.env` via `apply-db.sh` — no secret is in any committed
  manifest.
- App: Deployment, 2 replicas, rolling updates, stateless against Postgres.
- Images: moving to GHCR (public-IP nodes rule out the self-hosted insecure
  registry). Versioned tags via `deploy.sh`.
- TLS: cert-manager (v1.20.2) + Traefik + Let's Encrypt, covering **three**
  hostnames on one SAN cert — `zip.hsabren.co.uk`,
  `zip.derangedimagination.com`, `zip.saidtheape.com` (in setup; staging →
  prod).

---

## 2. What's already resilient (built and tested)

- **App survives Postgres restarting underneath it** — the pool validates
  connections on borrow and recycles dead ones; verified by restarting PG
  under a live app and seeing it recover on the next request.
- **App tolerates Postgres not being ready at startup** — connect-retry loop
  plus an init container that waits on `pg_isready`; verified.
- **Stateless app, 2 replicas, rolling updates** — one pod (or node) can go
  without taking the service down, as long as Postgres is reachable.
- **Self-healing** — readiness/liveness probes on `/api/health` restart or
  drain unhealthy pods automatically.
- **TLS auto-renewal** — cert-manager renews Let's Encrypt certs without
  intervention (once issuance works).

---

## 3. Failure points & resilience gaps

Ordered roughly by stakes.

### Data / persistence — **highest stakes**
- **No backups.** There is currently no copy of the Postgres data anywhere.
  A node loss, a bad migration, or an accidental `delete pvc` loses all
  users, attempts, and leaderboards permanently.
- **Postgres data is node-local.** The `local-path` PVC is a directory on
  `yellowland001`. If that node is lost or reimaged, the data is gone. If the
  node is merely drained, Postgres can't reschedule elsewhere (the volume is
  pinned to that node), so the DB — and thus the app — stays down until the
  node returns.
- **`local-path` does not enforce capacity.** The "2Gi" request isn't a
  limit; Postgres (or the registry, pre-GHCR) can grow until it fills the
  node's disk, which would take down everything on that node.

### Availability / single points of failure
- **Single Postgres** is the app's hard dependency. The app recovers
  automatically *once PG returns*, but while PG is down the app errors.
- **Single control-plane node.** If `redland001` dies, the cluster API is
  down — existing pods keep running on `yellowland001`, but nothing can be
  rescheduled or changed until it's back.
- **DNS points at one node.** All three hostnames → `redland001` only. If
  that node is down, the site is unreachable even if the other node is fine.
  The three domains also share one SAN cert, so they rise and fall together
  (and a DNS lapse on any one can stall renewal of the shared cert).
- **Traefik** typically runs as a single replica in k3s; brief ingress
  outage if its node fails, until it reschedules.

### Security
- **k8s API (6443) and SSH (22) are likely public.** A public Kubernetes API
  is a meaningful attack surface.
- **DB password is now kept out of git** (gitignored `.secrets.env`, Secret
  created out-of-band by `apply-db.sh`; only `.secrets.env.example` is
  tracked). Residual exposure remains: it's plaintext in `.secrets.env` on the
  dev machine and base64 (not encrypted) in the cluster datastore — hence the
  k3s secrets-encryption item below still stands. **If the real password was
  ever committed before this change, rotate it** — scrubbing history doesn't
  reach existing clones/forks/backups.
- **Secrets aren't encrypted at rest** by default in k3s — anyone with node
  or datastore access can read the Postgres password.
- **No app-level auth or rate limiting.** The API is anonymous and public;
  `/api/users` and `/api/attempts` could be spammed.

### Operational
- **Manual deploys** (build → push → rollout). Fine for one maintainer; no
  automated build or rollback.
- **No PodDisruptionBudget** — a node drain could evict both app replicas at
  once.
- **Additive-only schema migrations.** Adding columns is handled; anything
  destructive or reshaping would be manual and risky.

### Observability
- **No monitoring or alerting.** A filled disk, a failed cert renewal, or a
  crash-looping pod is discovered only when something visibly breaks.

### Deliberate design choices (not bugs)
- **`/api/health` is shallow** (doesn't ping the DB). This is intentional: a
  deep check would pull *every* app pod out of rotation the instant PG
  blips, turning a brief DB hiccup into a full outage. The shallow check plus
  connection recovery keeps pods up and lets them reconnect — the better
  trade-off for this app.

---

## 4. Remediations worth doing (proportionate)

| # | Fix | Why | Effort |
|---|-----|-----|--------|
| 1 | **Automated `pg_dump` backups** to off-node storage (Oracle Object Storage / S3), on a CronJob, with one tested restore | Removes the single worst outcome (total data loss). Nothing else matters as much. | Low–med |
| 2 | ~~Keep the real DB password out of git~~ — **DONE**: gitignored `.secrets.env` + `apply-db.sh` create the Secret out-of-band. (Rotate the password if it was committed earlier.) | Prevents credential leak via the repo | — |
| 3 | **Restrict 6443 and 22** to your own source IP in the Oracle security list | Large attack-surface reduction | Low |
| 4 | **Enable k3s secrets encryption at rest** (`--secrets-encryption`) | Sensible on public cloud VMs | Low |
| 5 | **PodDisruptionBudget** (minAvailable: 1) for the app | Keeps a replica up during node maintenance | Low |
| 6 | **External uptime check** hitting `https://zip.hsabren.co.uk/api/health` | Cheapest possible "is it down?" signal | Low |
| 7 | **Watch node disk usage** (local-path has no quota) | Avoids a full-disk outage going unnoticed | Near-zero |
| 8 | *(Optional)* second DNS A record → worker node | Crude redundancy if the primary node is down | Low |

The clear priority is **#1**. Everything below it is good hygiene; #1 is the
difference between "annoying outage" and "everything is gone."

---

## 5. Deliberately NOT doing (diminishing returns for this project)

- **HA Postgres** (replication / CloudNativePG operator) — large complexity
  for a hobby puzzle app; automated backups cover the realistic risk.
- **HA control plane** (3 k3s servers + embedded etcd) — sensible for
  production, overkill for two nodes you control.
- **Full observability stack** (Prometheus/Grafana/Loki) — an external uptime
  check gives 90% of the value for ~1% of the effort.
- **NetworkPolicies / service mesh** — negligible benefit at this scale.
- **CI/CD pipeline** — worthwhile only if deploy frequency rises; `deploy.sh`
  is enough for now.
- **Sealed Secrets / SOPS / Vault** — the gitignored-file + out-of-band Secret
  approach (now in place) is sufficient at this scale. SOPS+age (encrypted
  secret committed to git) or Sealed Secrets would be the upgrade if a
  GitOps/declarative workflow is wanted later.

---

## 6. Outstanding setup tasks (separate from resilience)

- Finish TLS issuance (staging → prod) and confirm all three:
  `https://zip.hsabren.co.uk`, `https://zip.derangedimagination.com`,
  `https://zip.saidtheape.com`.
- Complete the GHCR migration (login, private package, imagePullSecret) and
  **update `deploy.sh`** — its `REGISTRY`/`IMAGE` still point at the abandoned
  self-hosted registry (`redland001…:30500`).
- Build an **admin backend** so welcome-banner phrases and consent-card copy
  in `ui_text` can be edited by an admin without DB write access or code
  changes (interim method is direct SQL). *(Reminder carried forward.)*
- Add a safe HTTP→HTTPS redirect *after* the cert is stable (a global
  redirect can break the ACME HTTP-01 challenge if added too early).
