# Decisions Log

A single, shared, **append-only** record of *why* the project is the way it is.
State lives in `STATUS.md`, process in `DEPLOYMENT.md`, ownership in
`RESPONSIBILITY.md` — this file is **rationale and history**.

## How to use this file

- **Append-only, newest first.** Add new entries at the **top**. Never delete.
- **One entry per decision.** Date it `YYYY-MM-DD` and tag it with one of:
  - `[platform]` — shared infrastructure (storage, ingress, TLS, mail, DB, backups)
  - `[zip-game]` — the Trace/zip-game application
  - `[cross-cutting]` — affects both workstreams (the ones that have no single home)
- **Any chat may append its own entry.** This file is the explicit exception to
  the "one editor per file" rule in `RESPONSIBILITY.md` §4: entries are
  independent dated lines, so two chats appending never truly conflict. But
  **never edit or reformat someone else's entry.**
- **Supersede, don't rewrite.** If a later decision overturns an earlier one,
  add a **new** entry that references the old one (by date + title) and notes
  what changed. Leave the original in place — the history is the point.
- **Keep it short.** Decision in a line or two, the *why* in a couple more,
  and a `Refs:` pointer to the doc/section that carries the detail.
- *(If this ever outgrows one file, graduate to numbered ADRs — one file per
  decision under `decisions/`. Not needed yet.)*

---

### 2026-06-03 — [zip-game] GHCR migration completed for the trace image
**Decision:** The Trace image is now published to `ghcr.io/fireappleblack/trace`
and pulled by the cluster via a `ghcr-pull` imagePullSecret; `deploy.sh` builds,
pushes, and rolls versioned tags to GHCR. Side-loading (`localhost/trace:latest`)
and the abandoned in-cluster registry are retired.
**Why:** Completes the 2026-05-31 [cross-cutting] "Images via GHCR" decision,
which left the migration outstanding. Pull-secret is named `ghcr-pull` (the live
cluster's name); GHCR requires a **classic** PAT with `write:packages`
(fine-grained tokens are rejected). Credential follows the out-of-band,
never-committed pattern.
**Refs:** supersedes the "outstanding" status of 2026-05-31 [cross-cutting]
"Images via GHCR"; DEPLOYMENT.md §3; STATUS.md §1, §6.

### 2026-06-03 — [zip-game] Cheat mode is flagged and excluded from public stats
**Decision:** Add an optional cheat mode (shows the solution). Any attempt made
with it on is flagged (`cheated`), forced non-public, and excluded from public
leaderboards and aggregates. The server stores `cheated` on `attempts`, added to
the idempotent startup ADD COLUMN migration so it self-applies on deploy.
**Why:** Keep a learning aid available without letting it pollute honest
rankings; the additive migration means no manual `psql` on existing databases.
**Refs:** STATUS.md §3 (Operational — additive migrations); schema.sql, db.py.

### 2026-06-03 — [zip-game] Wiggliness is a first-class `w` URL parameter
**Decision:** Promote path "wiggliness" (turn ratio) from a seed-suffix scheme to
a first-class `w` URL parameter (0–4, default 2 = natural), with a slider on the
main UI. The daily puzzle stays canonical at the default, so shared/daily links
are unaffected.
**Why:** Cleaner than encoding it in the seed, and lets players tune difficulty
feel without changing the puzzle identity.
**Refs:** trace.html; IDEAS.md (leaderboard-key caveat noted there).

### 2026-06-03 — [zip-game] Onboarding shows a placeholder backdrop, not the real puzzle
**Decision:** During the onboarding/consent stages the board shows a *sample*
backdrop (a finished example, or the player's last solve) rather than the real
puzzle, which is generated but hidden until consent. The real puzzle is revealed
only when gameplay is enabled.
**Why:** The previous flow exposed the real puzzle inert on load, which let it be
studied before the timer started. The backdrop preserves the visual without
giving that head start.
**Refs:** STATUS.md §1 (Onboarding flow); trace.html.

### 2026-05-31 — [cross-cutting] Documentation model: four root docs by concern
**Decision:** Keep four top-level Markdown docs, each organised by *concern*, not
by workstream: `STATUS.md` (state & risk), `DEPLOYMENT.md` (canonical
deploy/operate process), `RESPONSIBILITY.md` (file ownership), `DECISIONS.md`
(this log). All live in the repo root so cross-references stay bare filenames.
**Why:** Each answers a distinct, whole-system question; splitting by workstream
fragments the story and leaves cross-cutting items homeless.
**Refs:** RESPONSIBILITY.md; STATUS.md header note.

### 2026-05-31 — [cross-cutting] DECISIONS.md is a single, append-only, tagged log
**Decision:** One shared decision log, reverse-chronological, entries tagged
`[platform]` / `[zip-game]` / `[cross-cutting]` — rather than per-workstream
files (`platform-decisions.md` etc.).
**Why:** The weightiest decisions (storage, registry, backups, the split itself)
are cross-cutting and have no clean single owner; a tag gives the filtering
benefit of a split without duplicating or fragmenting. Append-only entries make
two-chat editing a trivial, conflict-free merge.
**Refs:** RESPONSIBILITY.md §4 (append-only carve-out).

### 2026-05-31 — [platform] Directory split: `platform/` for shared infra (v0.3.0)
**Decision:** Introduce top-level `platform/` for shared infrastructure and
`wordpress/` for per-site templates; `trace-server/` remains the app. Moved
`cluster-issuers.yaml` into `platform/`. (Directory named `platform/`, chosen
over an earlier `project/` working name.)
**Why:** Make "who owns this file" answerable from its path. The split is
additive from here — `cluster-issuers.yaml` was the only file that moved.
**Refs:** RESPONSIBILITY.md §3.

### 2026-05-31 — [platform] TLS live via cert-manager + Let's Encrypt
**Decision:** cert-manager v1.20.1 with Let's Encrypt HTTP-01 solved through
Traefik; ClusterIssuers `letsencrypt-staging` and `letsencrypt-prod`; always
issue on staging first, then flip to prod. One shared SAN cert covers the three
`zip.*` domains.
**Why:** Automated issuance/renewal; staging avoids burning prod rate limits
while proving the path. Zip game is now live and trusted on all three domains.
**Refs:** DEPLOYMENT.md §5; STATUS.md §1.

### 2026-05-31 — [platform] Re-enabled bundled Traefik + servicelb
**Decision:** Remove the `--disable traefik` and `--disable servicelb` flags from
the k3s server args; use k3s's bundled Traefik + klipper servicelb.
**Why:** They had been disabled, so nothing served ingress or bound host 80/443.
The committed manifests assume Traefik (`ingressClassName: traefik`); re-enabling
is the least-friction path. klipper now binds 80/443 on both nodes.
**Refs:** DEPLOYMENT.md §1, §2.

### 2026-05-31 — [platform] RustDesk relay not used; ports closed
**Decision:** No self-hosted RustDesk relay. Close the previously-opened ports
(21115–21119/TCP, 21116/UDP) in the OCI security list.
**Why:** It was never installed (ports opened in anticipation). Closing them is
pure attack-surface reduction at zero cost.
**Refs:** STATUS.md §3 (security).

### 2026-05-31 — [platform] Longhorn is the sole default StorageClass (replicas 2)
**Decision:** Longhorn is the single default StorageClass, `numberOfReplicas: 2`.
`local-path` retained but **non-default**, for caches/scratch only. **Always set
`storageClassName: longhorn` explicitly** on every PVC.
**Why:** Replication across both nodes lets stateful pods survive a node loss
(no more node-pinning). Explicit class is mandatory because k3s re-marks
`local-path` default on upgrade and could otherwise misfile a database.
**Refs:** DEPLOYMENT.md §1, §7; STATUS.md §2, §3.

### 2026-05-31 — [cross-cutting] Postgres/MariaDB tuning baseline
**Decision:** Tune small DBs conservatively — `shared_buffers` 32–64 MB,
`work_mem` 4 MB, `max_connections` 20–30 — and keep app connection pools to 1–2
per worker. Fold into manifests as each DB is built.
**Why:** Caps the largest potential RAM consumers on 12 GB nodes before stacking
mail + WordPress; keeps total Postgres/MariaDB backend processes low.
**Refs:** STATUS.md §6.

### 2026-05-31 — [cross-cutting] Backups: logical dumps + Longhorn target → Object Storage
**Decision:** Off-cluster backups via a CronJob doing logical dumps
(`pg_dump`, and `mysqldump` once MariaDB lands, plus a Stalwart export) to Oracle
Object Storage, alongside a Longhorn backup target to the same bucket. One tested
restore. **Highest-priority outstanding item — do before adding more stateful
services.**
**Why:** Longhorn replication covers node loss but not corruption, bad
migrations, or accidental deletion. This is the gap between "annoying outage" and
"everything is gone."
**Refs:** STATUS.md §4 #1.

### 2026-05-31 — [cross-cutting] Images via GHCR (retire side-load + in-cluster registry)
**Decision:** Publish container images to GHCR (`ghcr.io/<owner>/...`); nodes pull
from there. Retire the `podman save` → `scp` → `k3s ctr images import` side-load,
and the abandoned in-cluster registry (`registry.yaml`).
**Why:** Public-IP nodes rule out the insecure in-cluster registry. GHCR removes
the per-node tar import; the Mac stays the build box and never needs k3s.
**Refs:** DEPLOYMENT.md §3; STATUS.md §6 (migration still outstanding).

### 2026-05-31 — [platform] Mail server: Stalwart, Mode A, Mailbaby smarthost
**Decision (not yet built):** Run Stalwart (single Rust container: JMAP + IMAP +
SMTP) on `longhorn` replicas-2. Start in **Mode A** — outbound relayed through
Mailbaby's smarthost (`relay.mailbaby.net:587`), local mailboxes, no inbound
port 25, no MX. Add inbound (Mode B) only if real external inboxes are needed.
**Why:** Single lightweight binary covers JMAP+IMAP; Mailbaby owns outbound
deliverability (sidesteps Oracle's outbound-25 block). Mode A needs no public
mail ports — simplest viable internal mail service.
**Refs:** to land under `platform/mail/`.

### 2026-05-31 — [platform] WordPress: pod-per-site, shared MariaDB
**Decision (not yet built):** Host WordPress as one pod per site (not one VM per
site), single replica each, backed by **one shared MariaDB** StatefulSet (a DB +
user per site) for low-traffic sites. WordPress requires MySQL/MariaDB — not the
zip game's Postgres.
**Why:** Pods, not VMs, are the unit of a site; a shared MariaDB is far kinder to
12 GB nodes than one engine per site. Capacity ~10–20 low-traffic sites
alongside the zip game and mail.
**Refs:** to land under `platform/mariadb/` and `wordpress/`.
