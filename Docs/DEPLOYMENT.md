# Deployment — Canonical Process

> **This document supersedes** the deploy instructions in `README.md`,
> `trace-server/README.md`, and the inline narrative in `deploy.sh`.
> When the process changes, update **this file** and treat it as the single
> source of truth. Older instructions defer to it.
>
> For *who owns which files* across the parallel workstreams, see
> **`RESPONSIBILITY.md`**.
>
> **Last updated:** 2026-05-31

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
- `kubectl -n trace delete secret trace-tls` — force a clean re-issue against the real CA (§5)
- `kubectl -n trace get certificate -w` — watch the trusted prod cert reach `READY=True` (§5)
- `echo | openssl s_client -connect zip.hsabren.co.uk:443 -servername zip.hsabren.co.uk 2>/dev/null | openssl x509 -noout -issuer` — verify the served issuer is LE production (§5)

**Routine app update**
- `podman build -f trace-server/Containerfile -t ghcr.io/<owner>/trace:<version> .` — build the ARM64 image (§3)
- `podman push ghcr.io/<owner>/trace:<version>` — push to GHCR; nodes pull from there (§3)
- `kubectl -n trace set image deploy/trace trace=ghcr.io/<owner>/trace:<version>` — rolling update to the new version (§6)
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
- **Images:** target registry is **GHCR** (`ghcr.io/<owner>/...`).
  *(Interim: the trace image is still side-loaded as `localhost/trace:latest`;
  GHCR migration pending — see §3.)*
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

Nodes are **aarch64**, so build for ARM64. From the repo root:

```
podman build -f trace-server/Containerfile -t ghcr.io/<owner>/trace:<version> .
podman login ghcr.io                       # GitHub PAT with write:packages
podman push ghcr.io/<owner>/trace:<version>
```

First time only — make the package public, or create a pull secret:

```
kubectl -n trace create secret docker-registry ghcr \
  --docker-server=ghcr.io --docker-username=<user> --docker-password=<PAT>
```

and add `imagePullSecrets: [{ name: ghcr }]` to the Deployment.

> **Interim (until migration done):** the image is built on the Mac and
> side-loaded into containerd on **each node** (`podman save` ->
> `k3s ctr images import`), referenced as `localhost/trace:latest`.
> `deploy.sh` still points at the retired in-cluster registry — repoint it to
> GHCR or stop using it.

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

# Flip to production:
kubectl -n trace annotate ingress trace \
  cert-manager.io/cluster-issuer=letsencrypt-prod --overwrite
kubectl -n trace delete secret trace-tls               # force a clean re-issue
kubectl -n trace get certificate -w                    # READY=True, now trusted
```

- **`dig ...`** — pre-flight: one unresolved SAN stalls the *entire* shared cert.
- **`get certificate,order,challenge`** — watches the auto-started staging
  issuance; cert-manager spins a temporary solver Ingress per SAN. Want each
  `challenge` to clear and `trace-tls` to reach `READY=True`. A browser warning
  on staging is the expected success signal (untrusted test CA).
- **`annotate ... letsencrypt-prod`** — flips the Ingress to the production
  issuer, once staging has proven the path.
- **`delete secret trace-tls`** — forces a clean re-issue against the production
  CA rather than reusing staging material.
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
  limits. A staging-cert browser warning is the success signal, not a fault.
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

---

*Maintenance: update this file whenever the deploy steps, image registry,
storage class, or cert flow change — including the Quick command sequence at the
top, which must stay in step with §2–§6. This is the canonical process — older
instructions in READMEs and scripts defer to it. Ownership of files is in
`RESPONSIBILITY.md`; state and risk in `STATUS.md`; rationale in `DECISIONS.md`.*
