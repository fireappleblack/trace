<!-- flatten:begin
     repo-path: Docs/DECISIONS.md
     generated: 2026-06-12T22:19:14Z by flatten.py — do not edit this block
flatten:end -->

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

### 2026-06-12 [zip-game] — Blanked-cell symmetry-breaking; deterministic generation
Added blanked-off cells to break board symmetry (no twin solutions from rotation/reflection). One-pen: one blank in the bottom-left quadrant (bottom ⌊R/2⌋ rows × left ⌊C/2⌋ cols), restricted to even (r+c) on odd×odd (mandatory for Hamiltonicity), and off the anti-diagonal on squares unless that empties the set (5×5 keeps a harmless residual anti-diagonal symmetry; uniqueness is solver-enforced regardless). Two-pen: fixed bottom-left-corner blank + one rolled X; the corner alone breaks every symmetry that moves it, so X must (a) avoid the other three corners — a symmetric blank-pair re-imposes a reflection/180° — and (b) on squares, avoid the anti-diagonal, the one reflection that fixes the corner. Two blanks keep two-pen's playable count odd (centre kiss survives). Rolled blank pinned to URL as bx (cell index); shared links reproduce. Breaks byte-identical legacy reproduction for all grids (accepted: early game, ~3 players). Generator: replaced backbite-from-snake with findHoledHamiltonian (Warnsdorff + connectivity + leaf-prune seed search over playable cells) + hole-aware backbiteMix; solver/walls/win-detection are blank-aware via playableCount()/Nplay. Determinism: removed all wall-clock branching from generation (was non-reproducible under load); bounded instead by deterministic node budgets (findHoledHamiltonian node cap; generateForDifficulty cumulative genNodes cap). De-risked + validated via Node harness incl. brute-force automorphism check across all 34 configs. v0.33.0.

### 2026-06-08 — [cross-cutting] flatten.py re-stamps the block when content changes
**Decision:** `flatten.py`'s `generated:` timestamp now tracks **last change**,
not just first injection. On each run, if a file's body (the block itself
ignored) differs from its mirrored copy under `flattened/`, the block's stamp is
refreshed to the current run time; an unchanged file is still left
byte-for-byte alone. A new `restamped` action/count is reported, the block
format is unchanged (the same 4-line begin / repo-path / generated / end), and
`--check` still flags an unflattened edit as drift (exit 1).
**Why:** A correct-path block was previously preserved verbatim, so its stamp
froze at first injection — e.g. the `Docs/*.md` blocks read 2026-06-06 while
their content was already 2026-06-08. The stamp is only useful if it moves when
the file does.
**Note:** The first run on this version re-stamps every file whose body changed
since its last flatten (those stale doc stamps included) and `flatten.py` itself;
steady-state runs with no edits stay byte-stable.
**Refs:** flatten.py `body_changed()`, `block_stripped()`, `ensure_comment(…,
restamp)`; builds on DECISIONS.md 2026-06-06 [cross-cutting] "Flattened
Claude-Project upload set is generated, not hand-maintained".

### 2026-06-08 — [zip-game] Two-pen kissed snake stays editable (undo/retrace fix)
**Decision:** A snake that has reached the shared centre ("kiss") must stay
draggable and undoable; previously its path locked the moment it touched the
kiss. Two behaviours changed: (1) you can now **grab a snake's head at the kiss
and drag it back** to retrace — but this is checked *after* tap-to-extend, so
tapping the kiss to **complete the other snake** still wins; (2) `handleEnd` no
longer clears `activePen`, so the **Undo button targets the snake you last
touched** instead of guessing by which pen is longer.
**Why:** The lock was a playability bug — there was no way to correct a misplaced
final move into the kiss. Ordering the centre-grab after extend preserves the
finish-the-second-snake gesture; retaining `activePen` makes Undo predictable.
**Refs:** `trace.html` `handleStartTwoPen()` (new branch 4, centre-head grab),
`handleEnd()`, Undo handler. Verified through the real pointer handlers: grab +
drag pops the kiss (path 13→12) and Undo removes it from the correct snake.

### 2026-06-07 — [zip-game] Two-pen "distinct shades" option (`diffshades`)
**Decision:** New binary control + URL param **`&diffshades=true|false`** (two-pen
only). `true` (default) keeps per-snake colour-coding (reddish Snake A / teal
Snake B). `false` paints every number dot one neutral shade, so a "3" in Snake A
is visually identical to the "3" in Snake B — the player must deduce which is the
next point in each snake, which is much harder. Toggling **rolls a fresh puzzle**, since the setting changes effective difficulty. Precedence mirrors `t`: explicit
param wins, bare visit restores preference, shared two-pen link without it →
default colour-coded. Drawn snake *paths* stay two-coloured (they show the
player's own progress); only the numbered dots go uniform.
**Refs:** `trace.html` `DIFF_SHADES`, `twoPenNumberFor()`, `.number.uniform`,
`#diffShadesToggle`/`#diffShadesRow`, parse/updateURL.

### 2026-06-07 — [zip-game] Point count decoupled from grid; per-mode caps
**Decision:** The number of numbered points is now an independent control, not a
function of grid size. **One-pen:** total points `5 … ⌊2·√area⌋` (square → 2×side,
so 8×8 → 5–16, 9×9 → 5–18; rectangles scale by area). **Two-pen:** points **per
snake**, **odd only**, `3 … pairMax` where `pairMax = largest odd ≤ ⌊√area⌋+1`
(8×8 → {3,5,7,9}); with the shared centre kiss, `m` per snake = a combined path of
`2m−1` numbered points. New first-class URL param `pts=` (omitted in auto mode).
A **chef's-choice dice** rolls a value in range (odd in two-pen) and writes it to
the URL, so a "random" puzzle stays shareable. `POINTS = 0` = **auto**: one-pen
falls back to the legacy difficulty×area count so **every existing classic link
without `pts` reproduces byte-identically**; two-pen derives an odd default from
difficulty.
**Why:** LinkedIn Zip happily threads 12+ points on 8×8 — the K↔grid coupling was
an artificial limit. Higher ceilings also make large grids *cheaper* to generate
(more waypoints → smaller unique-solution search).
**Refs:** `trace.html` `loneMaxPoints()`, `pairMaxPerSnake()`, `effectivePoints()`,
`pointsRange()`, `syncPointsUI()`, points-slider + `#pointsDice` wiring.

### 2026-06-07 — [zip-game] Rectangular grids (ROWS×COLS, 5..9 each)
**Decision:** Replaced the single square `SIZE` with `ROWS`×`COLS` (each 5–9),
giving all 25 combinations 5×5 … 9×9. `SIZE` was removed entirely (not aliased)
so any missed call site fails loudly rather than silently assuming square.
Backward-compatible **size token** for URLs/logging/leaderboards: a square keeps
its single-digit value (5–9, unchanged), a rectangle encodes as `rows*10+cols`
(55–99, no collision) — see `sizeToken()` / `applySizeToken()`. So **existing
square links, leaderboards, and logged attempts are byte-identical**; rectangles
get a 2-digit `size` code (the server stores it as-is; insights/leaderboard
grouping may want to learn the encoding later).
**Why:** Rectangles still contain Hamiltonian paths and broaden the game cheaply.
**Refs:** `trace.html` geometry refactor; grid `<select>` expanded to 25 options.

### 2026-06-07 — [zip-game] Backbite generator for new grid configs
**Decision:** Large/odd grids (esp. 9×9 = 81 cells) thrash the backtracking
Hamiltonian search. Added a deterministic **backbite generator** (boustrophedon
seed + seeded random backbite moves; O(N)/move, never fails) used for **all new
configs (rectangles, or any dimension of 9)**. Legacy squares ≤8×8 keep the
original DFS search, so their seeds/links reproduce exactly.
**Why:** Reliable, fast, fully seed-deterministic path generation where the
search-based generator timed out.
**Refs:** `trace.html` `backbiteHamiltonian()`, branch in `generateHamiltonian()`.

### 2026-06-07 — [zip-game] 9×9 is the unique-solution frontier (accepted limit)
**Decision:** Kept 9×9 selectable but accept it is heavy. Proving a 9×9 puzzle
*unique* requires exhausting an enormous path space; measured ~4/5 success at
~9 s for higher point counts, and **low point counts on 9×9 are effectively
infeasible**. Tiered the solver node cap (`area ≤ 64 → area·5000`, else
`area·9000`) to bound the freeze, and `newPuzzle()` now re-rolls the seed up to
3× on failure (fresh puzzles only — never a shared link) before the trivial
snake fallback. 8×8 and below stay fast (8×8 low-K ≈ 7/8 in a few seconds).
**Why:** Inherent cost — it's why LinkedIn's Zip stops at 8×8. The raised point
ceiling mitigates it (users/auto can pick higher, cheaper counts).
**Open:** if 9×9 proves annoying in practice, options are to exclude it or raise
its minimum point count. Awaiting real-play feedback.
**Refs:** `generateCandidate()` cap; `newPuzzle()` retry loop.

### 2026-06-07 — [zip-game] Two-pen ("two snakes") validated; per-snake odd points
**Decision:** The two-snake variant is complete. Generation uniqueness needs **no
solver change**: on an odd grid with the centre waypoint pinned to the path
midpoint, the existing classic enforcement already yields exactly one two-snake
solution (verified with an independent single-path counter — 5×5/7×7 100%, and
odd rectangles). Two-pen requires **both dimensions odd**. The points control is
**per snake** and odd (see the point-count entry). URL `t=1`; precedence: explicit
`t` wins, a shared seed with no `t` is classic, a bare visit restores preference.
**Refs:** `trace.html` two-pen subsystem, `setupTwoPen()`, `canAddPen()`,
`checkSolvedTwoPen()`, `pickWaypoints()` two-pen branch.

### 2026-06-06 — [cross-cutting] Flattened Claude-Project upload set is generated, not hand-maintained
**Decision:** `flatten.py` (stdlib-only, repo root) generates the `flattened/`
upload set from the live tree. Flattened names are
`<repo-prefix>-<dir-prefix…>-<originalname>` (e.g. `zg-pl-mdb-config.json`), the
map kept in `flattened/flatten.cfg`. The script also injects an idempotent,
datetime-stamped `repo-path:` comment at the head of each source file, so every
flattened copy self-documents its origin. Exclusion is driven by
`git check-ignore`; per-file/folder opt-outs live in the cfg `[flattenignore]`.
`flattened/` is a derived artifact and is gitignored.
**Why:** Hand-syncing flattened names against the real tree drifts — worse once
this is several repos. Generating from source, with a `--check` mode for a
pre-commit/CI gate, keeps Project and repo in lockstep. `.dockerignore` is
deliberately NOT an inclusion filter: it has no `git check-ignore` equivalent,
its syntax differs from gitignore, and it excludes files (docs, deploy scripts)
the Project needs.
**Refs:** flatten.py; DEPLOYMENT.md §8.

### 2026-06-06 — [zip-game] Client build version stamped into the client and logged on each attempt
**Decision:** Added a `TRACE_VERSION` constant to `trace.html`, auto-stamped by
`deploy.sh` at build time (idempotent regex on the value, so it always matches
the deployed image tag; defaults to `'dev'` when unstamped). It's shown subtly
in the footer, exposed as `window.TRACE_VERSION`, and attached to every attempt
as a new `client_version` column (client SCHEMA + sql.js migration, plus
`schema.sql`, `ALLOWED_ATTEMPT_COLUMNS`, and `ATTEMPTS_V2_COLUMNS` server-side).
**Why:** A single-file static client caches hard, so users run stale builds for
days — a version stamp is what separates "known bug, already fixed" from a live
regression, and lets an odd attempt row be tied to the exact client that wrote
it. **Logged, never trusted:** nothing reads `client_version` back into
leaderboard/scoring/gate logic; `insert_attempt` coerces it to `str(...)[:64]`
so a hostile client can't write an oversized blob (the parameterised INSERT
already handles injection); a missing/junk value never blocks a legitimate
attempt. Hiding the version is explicitly *not* treated as a security control —
the file is view-source anyway — so the backend stays hardened on the assumption
it's public. Stamping in place means the committed `trace.html` reflects the
last-deployed tag (a feature: the repo records what's live).
**Refs:** trace.html `TRACE_VERSION` + `snapshot()`; deploy.sh stamp step;
db.py `ALLOWED_ATTEMPT_COLUMNS`/`ATTEMPTS_V2_COLUMNS`/`insert_attempt`;
schema.sql `attempts.client_version`; DEPLOYMENT.md §3.

### 2026-06-06 — [zip-game] Walls slider minimum relabelled "Fewest walls" (was "No walls")
**Decision:** Renamed the walls slider's level-0 label from "No walls" to
"Fewest walls" (everywhere: `WALL_LABELS[0]`, the markup default, and the
slider's live/fallback strings). No behaviour change — level 0 still adds zero
*extra* walls.
**Why:** Level 0 means "no walls *beyond* what uniqueness enforcement needs",
not a guaranteed wall-free board — depending on the other parameters, some walls
are necessary for a unique solution. "No walls" overpromised, and forcing
regeneration until a board happened to need none would be wasteful. "Fewest
walls" states honestly what the minimum delivers.
**Refs:** trace.html `WALL_LABELS`, `syncWallsUI`, walls slider wiring;
builds on DECISIONS.md 2026-06-06 "Walls slider".
App up to Version 0.8.4

### 2026-06-06 — [platform] Front public sites with Cloudflare (CDN/WAF/DDoS) + origin lockdown
**Decision:** Put public sites — the zip game now, WordPress and future
résumé-piece sites next — behind Cloudflare. **Free** tier to start; **Pro**
($20/mo annual) per zone only where the managed WAF earns it (the busy, attacked
site). Lock the origin so ports 80/443 accept only Cloudflare's IP ranges —
enforced at the **OCI security list** (authoritative) with host `firewalld` as
defense-in-depth. A documented outage **fallback** (grey-cloud bypass) covers a
Cloudflare-edge failure like 2025-11-18.
**Why:** Offloads DDoS / edge-WAF / bot / rate-limiting and hides the origin, so
origin effort re-focuses on what Cloudflare can't do (pod hardening, egress
containment, post-exploitation limits). Per-zone pricing keeps cost minimal; the
bypass keeps the single-provider dependency survivable.
**Refs:** platform/cloudflare/README.md, platform/cloudflare/FALLBACK.md.

### 2026-06-06 — [platform] cert-manager → Let's Encrypt DNS-01 via Cloudflare
**Decision:** Migrate certificate issuance from HTTP-01 (via Traefik on port 80)
to **DNS-01** solved through the Cloudflare API — new ClusterIssuers
`letsencrypt-dns01-staging` / `letsencrypt-dns01-prod`, with the API token as an
out-of-band secret. Migrate each Ingress staging→prod with `cmctl renew`, never
secret-deletion.
**Why:** Locking the origin to Cloudflare IPs breaks HTTP-01 (Let's Encrypt
can't reach port 80 directly). DNS-01 needs no inbound port, so the lockdown is
clean; it also retires the port-80-redirect and rate-limit-by-deletion footguns
for good, and allows wildcards if ever wanted.
**Refs:** platform/cloudflare/cloudflare-dns01-issuer.yaml; refines the HTTP-01
mechanism of 2026-05-31 [platform] "TLS live via cert-manager + Let's Encrypt".

### 2026-06-06 — [platform] Origin keeps a browser-trusted LE cert, NOT a Cloudflare Origin CA cert
**Decision:** With Cloudflare in front (SSL mode **Full (Strict)**), the origin
continues to serve a publicly-trusted Let's Encrypt certificate (via DNS-01). Do
**not** switch the origin to a free Cloudflare Origin CA certificate.
**Why:** An Origin CA cert is trusted only by Cloudflare. During an outage bypass
(grey-cloud → visitors hit the origin directly), a browser-trusted cert is
essential or every visitor gets a TLS warning. The small convenience of Origin
CA is not worth breaking the fallback — recorded explicitly to guard against a
later "just use Origin CA" reversal.
**Refs:** platform/cloudflare/FALLBACK.md, platform/cloudflare/README.md.

### 2026-06-06 — [platform] WordPress runs on LEMP (Nginx + PHP-FPM), not LAMP
**Decision:** Each WordPress site is a **two-container pod** — a
`wordpress:*-fpm` (PHP-FPM) container + an `nginx:alpine` container sharing the
html volume, FastCGI over `127.0.0.1:9000` — driven by shared Nginx-vhost and
FPM-pool ConfigMaps. `pm = ondemand` with an explicit `pm.max_children` bounds
both idle memory and per-site DB connections.
**Why:** For many mostly-idle sites on 12 GB nodes, LEMP idles far cheaper than
Apache+mod_php (which keeps a PHP interpreter resident per worker), and
`pm.max_children` is the explicit dial that keeps the shared-MariaDB connection
budget honest. Refines the 2026-05-31 [platform] "WordPress: pod-per-site, shared
MariaDB" decision (which had assumed the single-container Apache image).
**Refs:** wordpress/ (lemp-base.yaml, site-template.yaml, apply-site.sh, README.md).

### 2026-06-06 — [zip-game] "Really Wiggly" (`w=4`) fix: target decision density, not max turns
**Decision:** Lowered the wiggly-end targets off their pathological ceiling
(`WIGGLE_TARGET[4]` 0.75 → 0.66, `WIGGLE_BIAS[4]` 1.0 → 0.62; `w3` similarly
eased) and **replaced the candidate scorer's long-straight-run *penalty* with a
decision-density *floor***. New `decisionDensity()` counts the interior cells
where the solution goes straight while an un-walled turn was available — the only
cells where a blind "always turn" diverges from the answer — and the scorer
penalises candidates below `DECISION_FLOOR_FRAC` (`{3:0.36, 4:0.30}` of interior
cells). `w=2` (natural) is untouched, so the daily and every existing link are
bit-identical.
**Why:** Max turn-ratio was self-defeating. Measured on 8×8 fiendish (Node
harness over the real generator core): "max wiggle" nearly *halved* the
straight-against-turn decision points (~31/puzzle at natural → ~18 at old `w=4`)
and left an exploitable low tail (min 10, 5% of puzzles under 12 such points), so
always-turning tracked the solution. High turn-ratio and high decision-density
are close to mutually exclusive, so the fix keeps the wiggly *look* (turn ratio
~0.67, still clearly the wiggliest band) while lifting the tail: new `w=4` min
decision points 17, 0% under 12, turn ratio essentially unchanged (0.688→0.669).
Constants are tuned against a *proxy* for human difficulty — a sensible starting
point to feel out by playing, not a proven optimum.
**Refs:** trace.html `WIGGLE_TARGET`/`WIGGLE_BIAS`/`DECISION_FLOOR_FRAC`,
`decisionDensity`, scorer in `generateForDifficulty`; IDEAS.md "Generation
tuning"; supersedes the "to fix" status of the 2026-06-03 IDEAS item.

### 2026-06-06 — [zip-game] Walls slider: a second, solution-safe difficulty lever
**Decision:** Added **walls** as a first-class puzzle parameter (level 0..4,
URL param `m` for *maze*, its own on-board slider, `trace.walls` localStorage
default) alongside `w`. A puzzle is now reproducible from
`(seed, size, difficulty, w, m)`. **Level 0 = no extra walls = today's exact
behaviour**, so a missing `m` (the daily, any old link) is unchanged.
`addExtraWalls()` layers walls *after* uniqueness enforcement, only on internal
edges the canonical solution does **not** use, up to `WALL_FRAC` of available
non-solution edges, deterministically via the seeded rng. The walls slider keeps
the seed and re-walls (like Grid/Difficulty), rather than rolling a new seed
(like Path).
**Why:** It's the obvious difficulty lever independent of wiggliness. The
solution-safety/uniqueness concern from the IDEAS note is handled *by
construction*: never walling a solution edge keeps the canonical path valid, and
adding a wall can only forbid edges (never create a route), so the solution count
can only drop — uniqueness is preserved or improved. Verified on a real solver
(6×6, all levels, many seeds): no solution edge ever walled, solver count stays
exactly 1, wall counts scale ~9.6→20.2 across levels 0→4. Difficulty targeting
sees the walled board because the final solve runs after `addExtraWalls`.
**Refs:** trace.html `WALL_FRAC`/`WALL_LABELS`/`addExtraWalls`, `generateCandidate`,
`parseURL`/`updateURL` (`m`), walls slider wiring; IDEAS.md "Generation tuning".

### 2026-06-05 — [platform] Use `cmctl renew`, not secret-deletion, for prod TLS flips
**Decision:** The staging→prod cutover no longer deletes the trace-tls secret.
Flip the issuer annotation, then `cmctl renew trace-tls -n trace` for a single
controlled re-issue that keeps the old secret until the new cert is Ready.
**Why:** Deleting the secret triggers re-issuance AND risks a second trigger
(generation bump) racing it — two issuances against the 5-per-168h budget from
one action, plus an untrusted-cert gap. Hit this 2026-06-05 (issuance #6 → 429
while a valid prod cert already sat in trace-tls-2).
**Refs:** DEPLOYMENT.md §5 (to update); supersedes the "delete secret" step there.

### 2026-06-05 — [platform] Decouple the three zip domains into per-host TLS secrets
**Decision (to do once clear of the rate limit):** Split the single 3-SAN cert
into one tls entry + secretName per host, so each domain has its own
5-per-168h budget and CT-log footprint.
**Why:** Two lockouts now on the shared SAN set; any re-issue gambles all three
domains against one combined budget. Per-host certs isolate that blast radius.
**Refs:** trace-k8s.yaml (existing comment foreshadows this); STATUS.md §3.

### 2026-06-05 — [platform] Shared MariaDB implemented; max_connections raised to 60 for the shared case
**Decision:** Authored the shared MariaDB StatefulSet (Longhorn, root secret
out-of-band, `healthcheck.sh` probes) with a tuning ConfigMap:
`innodb_buffer_pool_size` 256M, small per-connection buffers, and
`max_connections = 60` (container memory limit 768Mi).
**Why:** Refines the 2026-05-31 [cross-cutting] tuning baseline (20–30) for a
*shared* engine fronting 10–20 WP sites, where 30 risks "Too many connections".
The RAM-capping intent is preserved; keep per-site `pm.max_children` modest to
stay under it.
**Note:** Manifests authored this session; **not yet deployed** on the cluster.
**Refs:** platform/mariadb/mariadb.yaml; refines 2026-05-31 [cross-cutting]
"Postgres/MariaDB tuning baseline".

### 2026-06-05 — [platform] Backups implemented (manifests) — logical dumps + Longhorn target
**Decision:** Authored the backups stack: a nightly CronJob doing `pg_dump` +
per-DB `mariadb-dump` → Oracle Object Storage (rclone; tools-only image; script
shipped via ConfigMap), plus a Longhorn backup target and a restore helper.
Backups-first: protects Postgres immediately and picks up MariaDB automatically
once its secret exists.
**Why:** Implements the 2026-05-31 backups decision — the highest-priority gap
(corruption / bad migration / accidental delete, none of which Longhorn
replication covers). Per-DB MariaDB dumps restore per-site.
**Note:** Manifests authored this session; **not yet deployed or restore-tested**.
The "one tested restore" requirement is still outstanding.
**Refs:** platform/backups/; advances 2026-05-31 [cross-cutting] "Backups: logical
dumps + Longhorn target → Object Storage".

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
