<!-- flatten:begin
     repo-path: Docs/STATUS.md
     generated: 2026-06-12T22:33:13Z by flatten.py — do not edit this block
flatten:end -->

# Trace — Status & Resilience Review

**Checkpoint: 2026-06-13 (zip-game) · 2026-06-08 (platform)** — the zip-game
**Application** section was refreshed 2026-06-13 (multiple-solutions model + wriggliness scoring, v0.41.0);
the **Infrastructure** sections are as of 2026-06-08. Note: the newly-built MariaDB, backups,
WordPress (LEMP), and Cloudflare manifests are **authored but not yet
deployed/validated on the cluster** — recorded here and in `DECISIONS.md`, but
treat their cluster state as *pending* until deployed.

A snapshot of where the project stands, what's already resilient, where it
can fail, and which fixes are worth making before they hit diminishing
returns.

> **Process vs. state:** this document is the *state / risk* review. For *how to
> deploy and operate* the stack, see **`DEPLOYMENT.md`** (the canonical
> process doc). Keep the split clean — risk and status here, procedure there.

**Changed since the last checkpoint:**
- **Zip-game (2026-06-13, v0.41.0):** **Wriggliness scoring** landed. On solving, the
  status line shows `Solved · N turns` (N = direction changes), and on repeat solves
  of the same board adds `· fewest M` / `· most M` from a per-board best/most kept in
  browser local storage — so players can chase a least-/most-wriggly target. One-pen
  scores the path; two-pen sums both snakes. Validated (measure unit tests + end-to-end
  solve-integration; generation unchanged). Remaining: a **server-side leaderboard**
  for cross-player competition (an `app.py` task). See DECISIONS 2026-06-13.
- **Zip-game (2026-06-13, v0.40.0):** **Multiple solutions are now allowed** — the
  game no longer enforces a unique solution. Generation stopped adding walls for
  uniqueness and dropped the uniqueness solve entirely; it just lays the ordered
  nodes along one real Hamiltonian path (≥1 solution guaranteed by construction).
  That removed the solver from the generation hot path and **cut 9×9 generation from
  ~21s to ~2s** — the latency item is effectively closed. Play reframes around
  *choosing among* solutions: **wriggliness** competitions (fewest/most direction
  changes) and admin-curated **find-the-shape** challenges. Win-detection needed no
  change (it already accepted any path covering every non-blank cell and threading
  the nodes in order). Knock-ons: the two-pen rolled blank is now confined to the
  bottom-left quadrant (subsuming the old three-corner exclusion); walls (`m`) keep
  only their difficulty/variety role (plus solution-space sculpting for the admin
  tool); added a `solutionWriggliness()` measure; `DIFFICULTY` now drives only the
  auto node count. Headless-validated across all 34 configs (validity, blank rules
  incl. two-pen-in-quadrant, brute-force automorphism check, round-trip determinism,
  timing). The authoritative spec is now **`Docs/New-game-definition.md`**. **Not yet
  browser-play-tested.** See DECISIONS 2026-06-13.
- **Zip-game (2026-06-12):** Added **blanked-off cells** that break the board's
  symmetry, so rotations/reflections can't mint twin solutions — headless-validated
  across all 34 configs (incl. a brute-force automorphism check, uniqueness,
  centre-kiss, and full URL round-trip). One-pen blanks one cell in the bottom-left
  quadrant (even `(r+c)` only on odd×odd, which is mandatory for a Hamiltonian path;
  off the anti-diagonal on squares, bar 5×5 where that would empty the set). Two-pen
  keeps the fixed bottom-left-corner blank and adds one rolled `X` that avoids the
  other three corners and — on squares — the anti-diagonal: the corner alone breaks
  every symmetry except the one reflection that *fixes* it, and a symmetric blank-pair
  would re-impose one, so `X` carries those exclusions. The rolled blank is pinned to
  the URL as **`bx`**. Generator replaced with a hole-aware **`findHoledHamiltonian`**
  seed search (Warnsdorff + connectivity + leaf prune) + hole-aware backbite; the
  solver, walls, and win-detection now count `playableCount()`. **This breaks
  byte-identical legacy reproduction for all grids** (accepted — early game, ~3
  players). Also fixed a latent **reproducibility bug**: generation branched on
  wall-clock time and so could yield a different puzzle under load — now bounded by
  **deterministic node budgets** only, so shared `bx`/seed links reproduce on any
  machine (side effect: 9×9 generation fell from ~21s to ~5–9s). v0.33.0. **Not yet
  browser-play-tested.** See the 2026-06-12 `[zip-game]` entry in `DECISIONS.md`.
- **Platform (2026-06-08):** Authored the shared **MariaDB** StatefulSet (tuned
  for the shared case), the **off-cluster backups** stack (logical dumps +
  Longhorn target + restore helper), the **WordPress (LEMP)** per-site stack, and
  the **Cloudflare** edge pattern (DNS-01 issuer, origin lockdown, outage
  fallback). All **manifests-only so far — not yet deployed.** The TLS prod-flip
  procedure was also corrected to `cmctl renew` (never secret-deletion). See the
  2026-06-05/06-06 `[platform]` entries in `DECISIONS.md`.
- **Zip-game (2026-06-08):** A large client feature set landed and was
  headless-validated (generation, uniqueness, win-conditions, point ranges,
  randomiser invariants, classic regression): non-square **rectangular grids**
  (all 25 of 5×5…9×9 via ROWS×COLS, with a backward-compatible `size` token so
  square links/leaderboards stay byte-identical); **point count decoupled from
  grid size** (one-pen total `5…⌊2√area⌋`; two-pen **odd points per snake**
  `3…pairMax`; new `pts` URL param); the **two-snake "kissing" mode** (`t`) with
  a **`diffshades`** colour-coding option (a flip regenerates a fresh puzzle, so
  it can't be used as an untraceable difficulty cheat); **per-control 🎲 plus a
  "Surprise me" full-randomiser** (every rolled value written to the URL); a
  deterministic **backbite generator** for the new sizes; and a fix so a two-pen
  snake that reaches the kiss **stays editable** (drag-back / Undo). 9×9 remains
  the heavy unique-solution frontier. **Not yet browser-play-tested.** See the
  2026-06-07/06-08 `[zip-game]` entries in `DECISIONS.md`.
- **Zip-game & deploy (2026-06-03):** GHCR migration completed — image published
  to `ghcr.io/fireappleblack/trace`, pulled via the `ghcr-pull` imagePullSecret,
  with `deploy.sh` building/pushing/rolling versioned tags; side-loading and the
  self-hosted registry retired. Added cheat mode (flagged, excluded from public
  boards), wiggliness as a first-class `w` URL parameter with a main-UI slider,
  and an onboarding **placeholder backdrop** (the board no longer shows the real
  puzzle pre-consent — a sample/last-solve is shown instead). The server's
  additive ADD COLUMN migration now includes `cheated`, so it self-applies on
  deploy. **TLS regressed during that session** (the edge fell back to Traefik's
  self-signed cert after a duplicate-certificate rate-limit); **recovered
  2026-06-08** once the window passed and cert-manager re-issued — see §1/§6.
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
  public leaderboards), consent gate, local SQLite-in-browser persistence,
  optional server sync. Served by the Flask app (one canonical copy, no
  duplication).
- **Puzzle variety / controls (main UI + URL params):** adjustable path
  **wiggliness** (`w`) and **wall density** (`m`) sliders; **selectable grid** —
  all 25 rectangles 5×5–9×9 (ROWS×COLS), encoded in a backward-compatible `size`
  token (squares keep their single digit; rectangles use `rows*10+cols`);
  **decoupled point count** (`pts`) — one-pen total `5…⌊2√area⌋`, two-pen **odd
  points per snake** `3…pairMax`; a **two-snake "kissing" mode** (`t`, both grid
  dims odd) with a **`diffshades`** binary colour option (off = both snakes'
  numbers share one neutral shade, much harder; toggling regenerates); and
  **per-control 🎲 randomisers + a "🎲 Surprise me"** full-randomise. Per the
  settled rule, every randomised/rolled value is written back to the URL, so any
  puzzle — including a surprise one — is shareable and reproducible. **Blanked-off
  cells** break each board's symmetry so rotations/reflections can't mint twin
  solutions: one-pen removes one cell from the bottom-left quadrant; two-pen removes
  the fixed bottom-left corner plus one rolled cell (kept off the other corners, and
  off the anti-diagonal on squares). The rolled cell's index is pinned to the URL as
  **`bx`**, and two blanks keep the two-pen playable count odd so the centre kiss
  survives.
- **Generation (v0.40.0):** a hole-aware seed search (**`findHoledHamiltonian`** —
  Warnsdorff + connectivity prune + leaf prune over the *playable* cells) finds a
  Hamiltonian path that skips the blanked cells; small squares keep that path
  directly, larger and rectangular configs mix it with a hole-aware backbite. The
  ordered nodes are laid along that path, so **≥1 solution is guaranteed by
  construction**. Boards may now have **many** solutions — **uniqueness is no longer
  enforced** and the uniqueness solver is out of the generation path entirely, which
  cut 9×9 generation from ~21s to **~2s**. Generation is wall-clock-free, so a given
  seed + settings (`size`, `pts`, `w`, `m`, `bx`) reproduces the exact board on any
  machine. Byte-identical legacy reproduction is not preserved (accepted — DECISIONS
  2026-06-12 / 2026-06-13). The solver, walls, and win-detection all count
  `playableCount()`. (`enforceUniqueness`/`classify` and the node-budget caps remain
  in the source but unused by generation — `enforceUniqueness` is the basis for the
  planned admin solution-enumerator.)
- **Solutions & scoring (v0.40.0):** a board may admit many valid paths; players
  compete on **wriggliness** — the number of direction changes (fewest, or most).
  Win-detection accepts *any* path that covers every non-blank cell and threads the
  numbered nodes in order, so every valid route wins. **Wriggliness scoring landed in
  v0.41.0**: the solved line shows `Solved · N turns`, with a per-board best (fewest)
  and most kept in local storage (`· fewest M` / `· most M` on repeat solves);
  one-pen scores the path, two-pen sums both snakes. A **server-side leaderboard**
  for cross-player competition is still to come. An admin **find-the-shape** mode
  (pick an exact path — "the fish" — validated by exact match) and an offline
  solution **enumerator** (bounded by a solution cap, since counts explode on
  lightly-noded boards) are planned for the admin back-end. Authoritative spec:
  `Docs/New-game-definition.md`.
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
- TLS: cert-manager (v1.20.1) + Traefik + Let's Encrypt, covering **three**
  hostnames on one SAN cert — `zip.hsabren.co.uk`,
  `zip.derangedimagination.com`, `zip.saidtheape.com`. The 2026-06-03
  duplicate-certificate rate-limit (5 per exact SAN set per 168h) **expired
  2026-06-06 10:23 UTC**; cert-manager's backoff should have re-issued the
  trusted production cert automatically — **confirm with `kubectl -n trace get
  certificate trace-tls`** (expect `READY=True`, issuer Let's Encrypt prod).
  **Re-issue / staging→prod flip procedure: change the issuer annotation, then
  `cmctl renew` — NEVER delete the cert secret** (a double-trigger burned two
  rate-limit slots on 2026-06-05; see DECISIONS 2026-06-05 and DEPLOYMENT §5/§7).
  Migration to **DNS-01 via Cloudflare** is decided (DECISIONS 2026-06-06) and
  will replace the HTTP-01 mechanism. *(TLS issuers are Infrastructure-owned —
  platform workstream.)*
- **Shared MariaDB** *(authored, not yet deployed)*: one MariaDB StatefulSet on
  Longhorn for WordPress tenants (a DB + least-privilege user per site), tuned
  for the shared case (`innodb_buffer_pool_size` 256M, `max_connections` 60).
  Distinct from the app's Postgres. *(platform/mariadb/ — DECISIONS 2026-06-05.)*
- **WordPress (LEMP)** *(authored, not yet deployed)*: one two-container pod per
  site (Nginx + PHP-FPM) on the shared MariaDB; `pm.max_children` bounds per-site
  DB connections. *(wordpress/ — DECISIONS 2026-06-06.)*
- **Off-cluster backups** *(authored, not yet deployed/restore-tested)*: a nightly
  CronJob doing `pg_dump` + per-DB `mariadb-dump` → Oracle Object Storage, plus a
  Longhorn backup target and a restore helper. *(platform/backups/ — DECISIONS
  2026-06-05.)*
- **Cloudflare edge** *(decided/authored, not yet cut over)*: front public sites
  (CDN/WAF/DDoS), lock the origin to Cloudflare IPs, migrate cert-manager to
  DNS-01 via Cloudflare, with a documented outage fallback; origin keeps a
  browser-trusted LE cert (not Origin CA) for clean bypass. *(platform/cloudflare/
  — DECISIONS 2026-06-06.)*

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
  intervention. *(Resumed once the prod cert was re-issued after the 2026-06-06
  rate-limit window — confirm per §1.)*

---

## 3. Failure points & resilience gaps

Ordered roughly by stakes.

### Data / persistence — **highest stakes**
- **Backups authored but not yet deployed.** Longhorn replication protects
  against *hardware/node* loss, but **not** a bad migration, logical corruption,
  or an accidental `delete pvc` / namespace deletion — any of which still loses
  all users, attempts, and leaderboards. The off-cluster backups stack now
  **exists** (platform/backups/) but is **not yet deployed and has no tested
  restore**, so this gap is *closing, not closed*. Deploying it and running one
  restore is the top remaining task (see §4 #1).
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
  A second A record → the worker is now genuinely useful (§4 #8); the planned
  **Cloudflare** front (proxying both node IPs) also addresses this once cut over.
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
  `/api/users` and `/api/attempts` could be spammed. The planned **Cloudflare**
  edge (WAF + rate-limiting) is the intended mitigation for the public sites, and
  an **egress NetworkPolicy** for the WordPress tenant is planned to contain a
  compromised tenant (DECISIONS 2026-06-06).

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
| 1 | **Deploy the off-cluster backups** — the manifests now exist (platform/backups/); remaining is to deploy the CronJob, point it at Object Storage, and **run one tested restore** | Longhorn covers node loss; this covers corruption, bad migrations, and accidental deletion — the worst remaining outcome | Low |
| 2 | ~~Keep the real DB password out of git~~ — **DONE**: gitignored `.secrets.env` + `apply-db.sh` create the Secret out-of-band. (Rotate the password if it was committed earlier.) | Prevents credential leak via the repo | — |
| 3 | **Restrict SSH (22)** to your own source IP in the Oracle security list (6443 + k3s ports already private-subnet-only; RustDesk ports already closed) | Closes the last world-open port | Low |
| 4 | **Enable k3s secrets encryption at rest** (`--secrets-encryption`) | Sensible on public cloud VMs | Low |
| 5 | **PodDisruptionBudget** (minAvailable: 1) for the app | Keeps a replica up during node maintenance | Low |
| 6 | **External uptime check** hitting `https://zip.hsabren.co.uk/api/health` | Cheapest possible "is it down?" signal | Low |
| 7 | **Watch disk usage** — both node boot disks and aggregate Longhorn volume usage | Avoids a full-disk outage going unnoticed | Near-zero |
| 8 | *(Optional)* second DNS A record → worker node | Real redundancy now that both nodes bind 80/443 | Low |

The clear priority is still **#1** — but it is now *deploy + test* the backups
that already exist, not build them. Everything below it is good hygiene; #1 is
the difference between "annoying outage" and "everything is gone." Longhorn has
narrowed that gap (node loss is now survivable) but has **not** closed it until
backups are actually running and a restore has been proven.

---

## 5. Deliberately NOT doing (diminishing returns for this project)

- **HA Postgres** (replication / CloudNativePG operator) — large complexity for
  a hobby puzzle app; Longhorn now gives storage-level resilience and automated
  backups cover the rest of the realistic risk.
- **HA control plane** (3 k3s servers + embedded etcd) — sensible for
  production, overkill for two nodes you control.
- **Full observability stack** (Prometheus/Grafana/Loki) — an external uptime
  check gives 90% of the value for ~1% of the effort.
- **Service mesh** — negligible benefit at this scale. *(NetworkPolicies are no
  longer wholly off the table: an **egress** policy for the WordPress tenant is
  planned as part of the Cloudflare-era hardening (DECISIONS 2026-06-06), since
  the edge can't contain a compromised tenant's outbound traffic.)*
- **CI/CD pipeline** — worthwhile only if deploy frequency rises; `deploy.sh`
  (now on GHCR) is enough for now.
- **Sealed Secrets / SOPS / Vault** — the gitignored-file + out-of-band Secret
  approach (now in place) is sufficient at this scale. SOPS+age or Sealed
  Secrets would be the upgrade if a GitOps/declarative workflow is wanted later.

---

## 6. Outstanding setup tasks (separate from resilience)

**Zip-game (application):**
- **Browser play-test** of the new client features — rectangle rendering, two-snake
  visuals + the `diffshades` uniform shade reading as genuinely ambiguous, the dice /
  "Surprise me" controls, **the blanked-off cells (one-pen and two-pen) rendering as
  clear holes and feeling fair to play around**, the 9×9 feel on a real device, and
  **how a multiple-solution board feels** without the "one right answer" framing
  (v0.40.0). (All current validation is headless.)
- **9×9 latency — resolved (v0.40.0):** dropping uniqueness enforcement took 9×9
  generation from ~21s to ~2s, so the earlier keep / exclude / raise-points decision
  is no longer forced by performance. Any remaining call on 9×9 is now purely about
  *feel*, to be made during play-test. (See `DECISIONS.md` 2026-06-13.)
- **Wriggliness scoring — landed (v0.41.0):** each solution's turn-count is shown on
  solve, with a per-board best/most in local storage. **Remaining:** a server-side
  leaderboard so players compete across devices on fewest/most-wriggly (an `app.py`
  + API task, not yet started).

**Platform / other:**

- **Confirm TLS recovered** (regressed 2026-06-03 — see §1): the prod rate-limit
  window passed (**2026-06-06 10:23 UTC**) and cert-manager should have
  auto-issued the trusted cert — verify `kubectl -n trace get certificate
  trace-tls` shows `READY=True`. **If a re-issue is ever needed, change the
  issuer annotation then `cmctl renew trace-tls -n trace` — NEVER delete the
  secret** (DECISIONS 2026-06-05; DEPLOYMENT §5/§7). The DNS-01-via-Cloudflare
  migration is the next planned TLS change (DECISIONS 2026-06-06).
- Add a safe **HTTP→HTTPS redirect** once the cert is stable again (a global
  redirect added earlier would have broken the ACME HTTP-01 challenge).
- ~~Complete the **GHCR migration**~~ — **DONE (2026-06-03):** image on
  `ghcr.io/fireappleblack/trace`, pulled via `ghcr-pull`; `deploy.sh` repointed
  to GHCR; side-loading and the self-hosted registry retired.
- Build an **admin backend** so welcome-banner phrases and consent-card copy in
  `ui_text` can be edited by an admin without DB write access or code changes
  (interim method is direct SQL). *(Reminder carried forward.)*
- **Restrict SSH (22)** to your source IP (also §4 #3).
- **Deploy the new platform stacks** (manifests authored 2026-06-08, not yet on
  the cluster): the shared **MariaDB**, the **backups** CronJob (then run the one
  tested restore — §4 #1), and the **WordPress (LEMP)** per-site stack.
- **Cut over to Cloudflare**: onboard the sites, migrate cert-manager to
  **DNS-01 via Cloudflare**, lock the origin to Cloudflare IPs, and rehearse the
  outage bypass once (platform/cloudflare/ — DECISIONS 2026-06-06).
- *(Optional, performance)* tune Postgres for the small footprint
  (`shared_buffers` 32–64 MB, `work_mem` 4 MB, `max_connections` 20–30) and keep
  the app's connection pool small. *(The shared MariaDB is already tuned —
  DECISIONS 2026-06-05.)*
