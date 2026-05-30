# trace-server

Flask app that serves the single canonical `trace.html` (one directory up)
and provides a REST API for cross-user leaderboards, aggregates, and insights.

## Layout

```
project-root/
├── trace.html          ← the ONE client file (served by this server)
└── trace-server/
    ├── app.py          ← Flask routes; serves ../trace.html; owns the DB manager
    ├── db.py           ← data-access layer + Database connection manager
    ├── schema.sql      ← canonical schema (SQLite dialect; translated for PG)
    ├── requirements.txt
    ├── Containerfile    ← OCI image build (Podman / Docker)
    └── deploy/
        ├── postgres.yaml   ← dedicated PostgreSQL (StatefulSet) — apply FIRST
        └── trace-k8s.yaml  ← the app (Deployment/Service/Ingress) — apply SECOND
```

There is exactly one `trace.html`. `app.py` resolves it at `../trace.html`
by default (override with `TRACE_HTML_PATH`), so the standalone `file://`
copy and the served copy are the same file.

## Backends

The server speaks two database backends, chosen by `DATABASE_URL`:

- **SQLite** (`sqlite:///trace.db`) — the default for local dev. Zero setup,
  single file, WAL mode. One writer, so it doesn't scale past one process.
- **Postgres** (`postgresql://…`) — the default for the container / k3s
  deployment, backed by a dedicated Postgres database (see `deploy/`). The
  app is stateless against it and can run multiple replicas.

The `Database` manager in `db.py` handles both: for SQLite it keeps one
WAL connection; for Postgres it keeps a small per-process connection pool,
validates connections on borrow, recycles dead ones, and retries at startup.
That's what lets the app tolerate the separate Postgres container starting
late or restarting underneath it.

## Run locally (SQLite)

```bash
pip install -r requirements.txt
python app.py                 # dev server on :5000, SQLite (trace.db)
```

Open <http://localhost:5000>. `python app.py` uses Flask's dev server — fine
for local use; the container image uses gunicorn.

## Run locally against Postgres

Either point `DATABASE_URL` at it directly:

```bash
DATABASE_URL='postgresql://trace:secret@localhost:5432/trace' python app.py
```

…or supply the parts separately and let the app assemble the URL (the same
way the k3s deployment does — handles any password without escaping):

```bash
POSTGRES_HOST=localhost POSTGRES_PORT=5432 \
POSTGRES_USER=trace POSTGRES_DB=trace POSTGRES_PASSWORD='p@ss/w[o]rd#1' \
python app.py
```

Config resolution order: `DATABASE_URL` (if set) → `POSTGRES_HOST`-based
component assembly → `sqlite:///trace.db`.

## Build the container image (Podman)

Build from the **project root** (the directory containing `trace.html`):

```bash
cd /path/to/project-root
podman build -f trace-server/Containerfile -t localhost/trace:latest .
```

Quick local run against SQLite in a volume (no Postgres needed to smoke-test):

```bash
podman run --rm -p 5000:5000 \
  -e DATABASE_URL=sqlite:////data/trace.db \
  -v trace-data:/data localhost/trace:latest
```

(Docker works too — same commands with `docker`.)

## Deploy to k3s (with a dedicated Postgres)

k3s uses containerd, not Podman's image store, so a Podman-built image must be
side-loaded into k3s first.

**1. Build, export, and import the app image:**

```bash
cd /path/to/project-root
podman build -f trace-server/Containerfile -t localhost/trace:latest .
podman save localhost/trace:latest -o trace.tar
sudo k3s ctr images import trace.tar
sudo k3s ctr images ls | grep trace        # verify
```

(The Postgres image `postgres:16-alpine` is pulled by k3s from Docker Hub
normally — no side-loading needed for it, assuming the node has internet.)

**2. Set a real database password.** Edit `deploy/postgres.yaml` and change
`POSTGRES_PASSWORD` in the `trace-db` Secret — that's the only place it
appears. It may contain any characters; the app percent-encodes it when it
builds the connection URL, so symbols like `@ : / [ ] #` are fine. For
anything real, prefer creating the Secret out-of-band rather than committing
it.

**3. Apply — database first, then the app:**

```bash
kubectl apply -f trace-server/deploy/postgres.yaml
kubectl -n trace rollout status statefulset/trace-postgres

kubectl apply -f trace-server/deploy/trace-k8s.yaml
kubectl -n trace rollout status deploy/trace
```

The app's init container blocks on `pg_isready` until Postgres answers, and
the app itself retries the connection for ~60s — so even if you apply both at
once, the app waits for the database rather than crash-looping.

**4. Reach the app** — either:

- **Ingress (Traefik, bundled with k3s):** open <http://trace.localhost> on
  the k3s host (`*.localhost` resolves to 127.0.0.1). For a real hostname,
  edit the `host:` in `trace-k8s.yaml`.
- **Port-forward:** `kubectl -n trace port-forward svc/trace 8080:80`, then
  <http://localhost:8080>.

**Tear down** (deletes the database and its volume too):

```bash
kubectl delete -f trace-server/deploy/trace-k8s.yaml
kubectl delete -f trace-server/deploy/postgres.yaml
```

### Persistence & backups

Postgres data lives on a PVC provisioned from the StatefulSet's
`volumeClaimTemplates` (k3s `local-path`, a hostPath dir on the node).
Deleting `postgres.yaml` deletes that PVC and the data with it. To back up:

```bash
kubectl -n trace exec statefulset/trace-postgres -- \
  pg_dump -U trace trace > trace-backup.sql
```

### Scaling

The app `Deployment` runs `replicas: 2` and can go higher — it's stateless
now that all state is in Postgres. Postgres itself is a single instance
(`StatefulSet replicas: 1`); a single node is plenty for this workload.
Highly-available Postgres (replication/failover) is out of scope here and
usually handled by an operator (e.g. CloudNativePG) if you ever need it.

## API reference

### Meta
- `GET /api/health` — backend + current ToS version (also the k8s probe target)
- `GET /api/tos` — placeholder ToS text + FAQ items + version
- `GET /api/summary` — counts across all stored attempts

### Users
- `POST /api/users` — create / update profile, accept ToS
- `GET /api/users/<uid>` — fetch profile
- `DELETE /api/users/<uid>` — erase user + all their attempts

### Attempts
- `POST /api/attempts` — log one attempt (rejected unless the user has
  accepted the current ToS version)
- `GET /api/attempts?user_id=&limit=` — list attempts

### Leaderboards
- `GET /api/daily[?date=YYYY-MM-DD]` — today's daily puzzle metadata
- `GET /api/leaderboard/puzzle?seed=&size=&difficulty=` — top times for one puzzle
- `GET /api/leaderboard/daily[?date=YYYY-MM-DD]` — top times for today's daily

### Aggregates + insights
- `GET /api/aggregates[?size=&difficulty=]` — global medians / percentiles
- `GET /api/insights/personal/<uid>` — one user's own data, sliced
- `GET /api/insights?slice_by=&metric=&size=&difficulty=&min_samples=&verified_env_only=`
  — lifestyle slices filter to users with `share_lifestyle_in_aggregate=1`;
  groups below `min_samples` (default 20) are suppressed.

## Privacy enforcement

Both the client UI and `db.py` enforce the consent flags. `POST /api/attempts`
refuses any `user_id` that doesn't exist or has an outdated `tos_version`, so
the server is the source of truth on consent. Aggregate/leaderboard queries
JOIN `users` and filter on the relevant flag at the data layer.

## Schema portability notes

`schema.sql` is written in SQLite dialect (the in-browser client uses the same
shape). `db.py` translates it for Postgres on the fly:

- `INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL PRIMARY KEY`
- all other `INTEGER` columns → `BIGINT` — several store unix-millisecond
  timestamps (~1.7e12) that overflow Postgres's 32-bit `INTEGER`; SQLite's
  variable-width integers hide this, Postgres does not.

Parameter placeholders (`?` vs `%s`) and `lastrowid` vs `RETURNING id` are
likewise handled in the DAL.
