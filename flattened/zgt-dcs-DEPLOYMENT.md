<!-- flatten:begin
     repo-path: Docs/DEPLOYMENT.md
     generated: 2026-06-06T16:14:29Z by flatten.py — do not edit this block
flatten:end -->

# Deployment — Canonical Process

> **This document supersedes** the deploy instructions in `README.md`,
> `trace-server/README.md`, and the inline narrative in `deploy.sh`.
> When the process changes, update **this file** and treat it as the single
> source of truth. Older instructions defer to it.
>
> For *who owns which files* across the parallel workstreams, see
> **`RESPONSIBILITY.md`**.
>
> **Last updated:** 2026-06-05

---

## Quick command sequence


The whole deploy, top to bottom — the scannable path. Each line carries a
one-clause effect and a pointer to the section that explains it in full; the
detail lives there, this is the executable summary.

**One-time prerequisites (fresh cluster only)**
- `kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.20.1/cert-manager.yaml` — installs cert-manager + its CRDs (§2)
- `kubectl apply -f platform/cluster-issuers.yaml` — creates the LE staging + prod issuers; set a real email first (§2)
- *(assumed already in place: k3s with Traefik + servicelb enabled; Longhorn as sole default StorageClass, replicas 2 — §1/§2)*

**Deploy the stack**
- `./apply-db.sh` — creates the Postgres credentials Secret out-of-band (§4)
- `kubectl apply -f trace-server/deploy/postgres.yaml` — dedicated Postgres StatefulSet on Longhorn (§4)
- `kubectl apply -f trace-server/deploy/trace-k8s.yaml` — app Deployment + Service + Ingress; the Ingress annotation triggers cert issuance (§4)

**Issue TLS (staging → prod)**
- `dig +short zip.hsabren.co.uk zip.derangedimagination.com zip.saidtheape.com` — confirm all three SANs resolve before issuing (§5)
- `kubectl -n trace get certificate,order,challenge` — watch staging issuance reach `READY=True` (§5)
- `kubectl -n trace annotate ingress trace cert-manager.io/cluster-issuer=letsencrypt-prod --overwrite` — flip to the production issuer (§5)
- `cmctl renew trace-tls -n trace` — request **one** controlled prod re-issue; keeps the old secret until the new cert is Ready (§5). **Do NOT `delete secret trace-tls`** — see §5/§7
- `kubectl -n trace get certificate -w` — watch the trusted prod cert reach `READY=True` (§5)
- `echo | openssl s_client -connect zip.hsabren.co.uk:443 -servername zip.hsabren.co.uk 2>/dev/null | openssl x509 -noout -issuer` — verify the served issuer is LE production (§5)

**Routine app update**
- `export REPO_OWNER=fireappleblack` - export shell variables for the... 
- `export APP_VERSION=v0.8.0` - ...podman and kubectl commands below:
- `podman build -f trace-server/Containerfile -t ghcr.io/$REPO_OWNER/trace:$APP_VERSION .` — build the ARM64 image (§3)
- `podman push ghcr.io/$REPO_OWNER/trace:$APP_VERSION` — push to GHCR; nodes pull from there (§3)
- `kubectl -n trace set image deploy/trace trace=ghcr.io/$REPO_OWNER/trace:$APP_VERSION` — rolling update to the new version (§6)
- `kubectl -n trace rollout status deploy/trace` — block until the rollout is healthy (§6)

---

## 0. Scope

How to deploy and operate the Trace / zip-game stack on the k3s cluster.
The **Quick command sequence** above is the fast path; the sections below are
the detail. Environment facts that rarely change are in §1; the deploy steps are
§3–§5; routine operations in §6; the gotchas that have bitten us in §7.

---

## 1. Environment (rarely changes)

- **Cluster:** 2-node k3s, Oracle Ampere **ARM64** (Oracle Linux 10).
  - `redland001` — control-plane — private `10.0.0.193`, public (edge-NAT) `141.147.107.161`, AD-1.
  - `yellowland001` — worker — private `10.0.0.187`, AD-3.
  - Nodes hold **only private IPs**; the public address is Oracle **edge NAT**.
    Both nodes bind host 80/443 (Traefik via klipper `servicelb`).
- **Ingress:** Traefik (k3s bundled) + servicelb. `ingressClassName: traefik`.
- **Storage:** Longhorn is the **sole default** StorageClass, `numberOfReplicas: 2`
  (volume replicated across both nodes -> survives a single node loss).
  `local-path` is retained but **non-default**, for caches/scratch only.
- **TLS:** cert-manager (v1.20.1) + Let's Encrypt HTTP-01 via Traefik.
  ClusterIssuers: `letsencrypt-staging`, `letsencrypt-prod`.
- **Images:** **GHCR** (`ghcr.io/<owner>/...`; the zip game is
  `ghcr.io/fireappleblack/trace`), pulled via the `ghcr-pull` imagePullSecret.
  *(Migration complete — side-loading and the in-cluster registry retired; §3.)*
- **Domains (zip game):** `zip.hsabren.co.uk`, `zip.derangedimagination.com`,
  `zip.saidtheape.com` — all resolve to a node public IP, served on one shared
  SAN cert.

---

## 2. One-time prerequisites (already in place)

Recreate only on a fresh cluster.

1. k3s installed **without** `--disable traefik` / `--disable servicelb`
   (both must be enabled).
2. Longhorn installed; set as **sole default** SC; `default-replica-count = 2`.
3. cert-manager installed:
   ```
   kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.20.1/cert-manager.yaml
   ```
   Wait for all three pods (`cert-manager`, `cainjector`, `webhook`) to be
   `Running` — the webhook validates the issuer resources below.
4. ClusterIssuers applied with a **real email** in both:
   ```
   kubectl apply -f platform/cluster-issuers.yaml
   ```
5. DB Secret created **out-of-band** (never in git):
   ```
   ./apply-db.sh        # reads gitignored .secrets.env
   ```
6. OCI security list: 80/443 open to the world; SSH (22) restricted to your IP;
   6443 + k3s ports scoped to `10.0.0.0/24`. **Check both layers** — the OCI
   security list *and* host `firewalld`.

---

## 3. Build & publish the image (GHCR — canonical)

Nodes are **aarch64**, so build for ARM64. For the zip game, `<owner>` is
`fireappleblack` (image `ghcr.io/fireappleblack/trace`). From the repo root:

```
podman build -f trace-server/Containerfile -t ghcr.io/fireappleblack/trace:<version> .
echo $CR_PAT | podman login ghcr.io -u fireappleblack --password-stdin
podman push ghcr.io/fireappleblack/trace:<version>
```

`$CR_PAT` must be a **classic** GitHub PAT with `write:packages` — GHCR rejects
fine-grained tokens.

The package is **private**, so the cluster needs a pull secret (one-time):

```
kubectl -n trace create secret docker-registry ghcr-pull \
  --docker-server=ghcr.io --docker-username=fireappleblack --docker-password=$CR_PAT
```

`trace-k8s.yaml` references it via `imagePullSecrets: [{ name: ghcr-pull }]`.
Note: `kubectl set image` can't add that line to a running Deployment — when
first switching to GHCR, **apply the manifest once** so the pull secret lands
(see §7).

> In normal use you don't run these by hand: **`deploy.sh <version>`** builds,
> pushes, and rolls a versioned tag to GHCR in one step.

---

## 4. Full deploy from scratch (ordered)

```
./apply-db.sh                                          # 1. DB Secret (out-of-band)
kubectl apply -f trace-server/deploy/postgres.yaml     # 2. DB (StatefulSet, longhorn PVC)
kubectl apply -f trace-server/deploy/trace-k8s.yaml    # 3. app + Service + Ingress
kubectl apply -f platform/cluster-issuers.yaml         # 4. shared TLS issuers (if not already)
```

- **`./apply-db.sh`** — creates the Postgres credentials `Secret` in the `trace`
  namespace from the gitignored `.secrets.env`, via
  `kubectl create secret --from-env-file` (so characters like `&` aren't mangled
  by the shell). The real password never lives in a committed manifest.
- **`postgres.yaml`** — the zip game's dedicated Postgres `StatefulSet` (1
  replica) + `Service`, on a Longhorn PVC. The app's own DB, distinct from the
  future shared MariaDB.
- **`trace-k8s.yaml`** — the app `Deployment` (2 replicas), `Service`, and the
  `Ingress` for the three `zip.*` hosts. The Ingress carries
  `ingressClassName: traefik`, a `tls:` block naming secret `trace-tls`, and the
  `cert-manager.io/cluster-issuer: letsencrypt-staging` annotation — which
  triggers automatic certificate issuance once cert-manager + issuers exist.

Every PVC **must** set `storageClassName: longhorn` explicitly (see §7).
Then run the cert flow (§5).

---

## 5. TLS issuance (staging -> prod)

The Ingress ships annotated `letsencrypt-staging`. Prove it, then flip.

```
# DNS for ALL three SANs must resolve to a node public IP first:
dig +short zip.hsabren.co.uk zip.derangedimagination.com zip.saidtheape.com

# Watch staging issuance reach READY=True (browser will warn — that IS success):
kubectl -n trace get certificate,order,challenge

# Flip to production, then request ONE controlled re-issue.
# DO NOT delete the trace-tls secret to force it (see §7) — that can
# double-trigger and burn two of the 5/168h slots, and serves an untrusted
# cert in the gap. cmctl renew keeps the old secret until the new one is Ready.
kubectl -n trace annotate ingress trace \
  cert-manager.io/cluster-issuer=letsencrypt-prod --overwrite
cmctl renew trace-tls -n trace                         # one controlled re-issue
kubectl -n trace get certificate -w                    # READY=True, now trusted
```

- **`dig ...`** — pre-flight: one unresolved SAN stalls the *entire* shared cert.
- **`get certificate,order,challenge`** — watches the auto-started staging
  issuance; cert-manager spins a temporary solver Ingress per SAN. Want each
  `challenge` to clear and `trace-tls` to reach `READY=True`. A browser warning
  on staging is the expected success signal (untrusted test CA).
- **`annotate ... letsencrypt-prod`** — flips the Ingress to the production
  issuer, once staging has proven the path.
- **`cmctl renew trace-tls`** — requests a single, controlled re-issue against
  the production CA, keeping the existing secret in place until the new cert is
  Ready (no untrusted-cert gap, no stray second trigger). `cmctl` is the
  cert-manager CLI — install once from
  https://cert-manager.io/docs/reference/cmctl/ . **Do NOT `delete secret
  trace-tls` to force issuance** (the old runbook step): on the prod issuer that
  both triggers a re-issue *and* risks a generation-bump re-trigger racing it,
  spending two slots from one action — exactly the 2026-06-05 lockout (§7).
- **`get certificate -w`** — watches the trusted prod cert reach `READY=True`.

Verify the trusted cert (independent of browser cache):

```
echo | openssl s_client -connect zip.hsabren.co.uk:443 \
  -servername zip.hsabren.co.uk 2>/dev/null | openssl x509 -noout -issuer
```

-> should show a Let's Encrypt **production** issuer (no "STAGING").

---

## 6. Routine operations

| Task | Command |
|------|---------|
| Update app | push new `:version` to GHCR -> `kubectl -n trace set image deploy/trace trace=ghcr.io/<owner>/trace:<version>` (rolling update, no downtime) |
| Watch rollout | `kubectl -n trace rollout status deploy/trace` (blocks until healthy) |
| Rollback | `kubectl -n trace rollout undo deploy/trace` |
| Logs | `kubectl -n trace logs deploy/trace -f` |
| Health | `curl -fsS https://zip.hsabren.co.uk/api/health` |
| Storage health | `kubectl -n longhorn-system get volumes.longhorn.io` (want `healthy`) |
| Confirm default SC | `kubectl get storageclass` (exactly one `(default)`, on `longhorn`) |

---

## 7. Gotchas (hard-won — read before deploying)

- **Always set `storageClassName: longhorn` on every PVC.** k3s re-marks
  `local-path` as default on upgrade; an unspecified class can silently land a
  database on node-pinned local-path. Re-check `kubectl get storageclass`
  after any k3s upgrade.
- **Staging before prod, always.** Let's Encrypt production has tight rate
  limits — notably the **duplicate-certificate** limit: 5 certs per *exact* SAN
  set per 168h. Iterate on **staging**; touch prod **once**. A staging-cert
  browser warning is the success signal, not a fault.
- **Never force a prod re-issue by deleting `trace-tls` — use `cmctl renew`.**
  On the prod issuer, deleting the secret triggers a fresh issuance (burns one
  slot) *and* a near-simultaneous generation bump can re-trigger a second order
  that races it — so one manual action spends **two** of the five slots, and
  the site serves Traefik's default (untrusted) cert in the gap. The
  three `zip.*` names share **one** exact-identifier set, so the budget is
  shared across all three: a double-trigger can lock out every domain at once.
  This is the **second** lockout from this pattern (2026-06-03 recreate cycles;
  2026-06-05 a double-trigger hit issuance #6 → 429 while a valid prod cert
  already sat in `trace-tls-2`). The recovery is to **wait** — the 429 error
  carries an exact `retry after` timestamp, and cert-manager's own backoff
  re-orders and populates `trace-tls` automatically once clear. A rejected
  (429) order does not burn a slot; only a *successful* issuance does. Going
  forward: flip the annotation, then `cmctl renew trace-tls -n trace`, and don't
  touch the secret. (Structural fix under consideration: decouple the three
  domains into per-host `tls:` secrets so each has its own 5/168h budget — see
  DECISIONS.md 2026-06-05.)
- **Add the HTTP->HTTPS redirect only *after* the prod cert is stable.** A
  global redirect breaks the HTTP-01 challenge (which serves on plain port 80).
  *(Still outstanding for trace.)*
- **All SAN hostnames must resolve before issuing** the shared cert — one
  missing DNS record stalls the whole certificate.
- **OCI `EXTERNAL-IP` shows the private `10.0.0.x` — that's correct**, not a
  fault. Public reachability is Oracle edge NAT; don't force the public IP into
  the service.
- **Two firewall layers:** the OCI security list *and* host `firewalld`.
  Opening a port in one does not open it in the other.
- **Browsers cache staging certs per-domain.** If a domain warns after the prod
  flip but `openssl` confirms the cert is valid, it's the browser's cached
  state (check in Incognito), not the server.
- **Postgres password drift.** Changing the `trace-db` Secret does **not** change
  the password Postgres already baked at first `initdb` on its PVC. Old pods keep
  the original; a new pod reads the new Secret → `password authentication failed`.
  Reconcile *both* sides — make the Secret match the DB (copy from a working pod)
  or change the DB to match the Secret (`\password`) — never edit the Secret
  alone. (Hit 2026-06-03 during the GHCR rollout.)
- **`kubectl set image` can't add `imagePullSecrets`.** Switching to a private
  registry needs the pull secret *and* an `imagePullSecrets` reference on the
  Deployment; `set image` only swaps the image tag. Apply the manifest once so
  the live Deployment carries the secret, or new pods sit in `ImagePullBackOff`.

---

## 8. Keeping the Claude Project in sync (flatten.py)

Out-of-band from the cluster: `flatten.py` (repo root) mirrors the repo into
`flattened/` under collision-free names for upload to the Claude Project, and
stamps each source file's head with its repo-relative path. Run it after
changing any file that lives in the Project.

```
# First run in a repo (interactive — prompts for repo + folder prefixes):
python3 flatten.py

# Routine resync (uses the saved prefixes; cleans up renamed/deleted files):
python3 flatten.py -y --prune

# Drift gate for a pre-commit hook / CI (writes nothing; exit 1 if out of sync):
python3 flatten.py --check
```

- Flattened names are `<repo-prefix>-<dir-prefix…>-<name>` (e.g.
  `zg-srv-dep-deploy.sh`); the prefix map and any opt-outs live in
  `flattened/flatten.cfg` (hand-editable). At a folder prompt, Enter accepts the
  suggested token; `-` skips the folder.
- Exclusion is driven by `git check-ignore`, so gitignored secrets/caches never
  reach the Project. `.dockerignore` is intentionally not consulted — it would
  drop docs you need (see DECISIONS.md 2026-06-06).
- Then upload the contents of `flattened/` to the Project. One repo = one
  prefix, so several repos can share a Project without name clashes.
- `flattened/` is a generated artifact — keep it in `.gitignore`.

---

*Maintenance: update this file whenever the deploy steps, image registry,
storage class, or cert flow change — including the Quick command sequence at the
top, which must stay in step with §2–§6. This is the canonical process — older
instructions in READMEs and scripts defer to it. Ownership of files is in
`RESPONSIBILITY.md`; state and risk in `STATUS.md`; rationale in `DECISIONS.md`.*

**Version stamping (automatic).** `deploy.sh <version>` rewrites the
`TRACE_VERSION` constant in `trace.html` to `<version>` before the build, so the
served client reports exactly which image it came from (footer tag,
`window.TRACE_VERSION`, and the `client_version` column on every logged attempt).
The rewrite is idempotent — it edits the *value*, so it never rots and is safe to
re-run — and it leaves the committed `trace.html` showing the last-deployed tag.
A live client reporting `dev` means an **unstamped** build was served (someone
built without `deploy.sh`, or the constant got renamed and the stamp's
"TRACE_VERSION not found" warning was missed). `client_version` is stored for
troubleshooting only and is never trusted by the server (bounded to 64 chars,
never read back into any logic), so no deploy step depends on it.

> If you ever build by hand instead of via `deploy.sh`, stamp it yourself first:
> ```
> sed -i.bak -E "s/(const TRACE_VERSION = ')[^']*(';)/\1<version>\2/" trace.html && rm -f trace.html.bak
> ```
