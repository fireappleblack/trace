<!-- flatten:begin
     repo-path: trace-admin/README.md
     generated: 2026-06-21T17:35:52Z by flatten.py — do not edit this block
flatten:end -->

# trace-admin

A **separate** admin back-end for Trace. The public app (`trace-server/`) and
the player client (`trace.html`) carry **no admin code and no admin API calls**.
This service shares the game's dedicated Postgres by importing the *same* data
layer (`trace-server/db.py`) — one source of truth — and exposes only admin
operations, behind a login.

## What it does (v1)

- **Multi-admin accounts + roles** — a strict hierarchy: **cleric** (edit site
  wording) < **admin** (+ game design) < **superadmin** (+ account/role
  management; audit/logs deferred). A superadmin creates accounts and assigns
  roles; everyone manages their own password.
- **UI-text editor** (cleric and up) — create / edit / activate / delete the
  `ui_text` rows: welcome-banner phrases, consent / data-protection card, ToS,
  FAQ. Live the moment they're saved.

Find-the-shape authoring + the bounded solution enumerator are **phase 2** (see
`Docs/DECISIONS.md`); they'll be gated to the **admin** role.

## Architecture

```
trace-admin/
  app_admin.py     Flask service: auth (login/session/CSRF/rate-limit), UI-text CRUD
  admin.html       single-file admin client (login shell + editor; no build step)
  Containerfile    image; build from the PROJECT ROOT (needs ../trace-server/db.py)
  requirements.txt Flask + gunicorn + psycopg2-binary
  deploy/
    admin-k8s.yaml      Deployment / Service / Ingress (namespace: trace)
    apply-admin.sh      create the trace-admin-secrets Secret out-of-band
    .secrets.env.example
```

`app_admin.py` imports `db.py` from `../trace-server` (mirrored in the image at
`/app/trace-server/`), so the schema and queries never diverge between the two
services. `db.py` gained `admin_list/create/update/delete_ui_text`; the public
app still only ever **reads** active rows via `get_ui_text`.

## Auth (accounts + roles)

- Accounts live in the `admin_users` table; login is **username + password**.
  Passwords are hashed with Werkzeug; the session is a signed HttpOnly
  SameSite=Strict cookie (`ADMIN_SECRET_KEY`); a per-session CSRF token must be
  echoed in `X-CSRF-Token` on every write; login is rate-limited per client IP.
- **Roles** (`cleric` < `admin` < `superadmin`) are a strict hierarchy enforced
  by a one-line `require_rank(min)` gate per route.
- **Bootstrap superadmin:** `ADMIN_USERNAME` (default `root`) + `ADMIN_PASSWORD`
  seed/refresh ONE break-glass superadmin at every startup, so you can always
  get back in via the secret + a restart. Manage that account's password via the
  secret, not the UI (the UI value is overwritten on restart).
- The intended deployment also sits behind an **edge gate** (Cloudflare Access /
  IP allowlist); app-level login is defense in depth, not the only wall.

## Build & deploy

```bash
# Build (PROJECT ROOT as context):
cd /path/to/project-root
podman build -f trace-admin/Containerfile -t ghcr.io/fireappleblack/trace-admin:v0.1.0 .
podman push ghcr.io/fireappleblack/trace-admin:v0.1.0

# Secret, then apply (after trace-server/deploy/postgres.yaml is up):
cd trace-admin/deploy
cp .secrets.env.example .secrets.env && $EDITOR .secrets.env
./apply-admin.sh
kubectl apply -f admin-k8s.yaml
```

**Infra-lane prerequisites for the public subdomain** (`admin.zip.hsabren.co.uk`):
DNS record → node IP; cert issuer coverage (staging → prod, `cmctl renew`, never
delete the secret); and an edge gate in front. See the header of `admin-k8s.yaml`.

## Local dev

```bash
cd trace-admin
ADMIN_PASSWORD=dev ADMIN_SECRET_KEY=dev-key python3 app_admin.py   # http://127.0.0.1:5001
```
With no `POSTGRES_*`/`DATABASE_URL`, it uses a local sqlite file (seeded UI text),
so you can click around the editor without the cluster.
