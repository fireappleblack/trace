# biglabel — static label/PDF generator (biglabel.saidtheape.com)

A single-page app (`Biglabel.html`) that builds an order-label PDF with driver/
vehicle **QR codes** entirely **in the browser** (jsPDF + html2canvas + qrcode).
**No backend, no database, no secrets** — so it's hosted as static content by a
tiny hardened nginx, using the same k3s / GHCR / Traefik / cert-manager /
Cloudflare principles as Trace, just without the Flask/Postgres layer (which it
doesn't need).

## Layout

```
biglabel/
├── Biglabel.html            # the app (client-side PDF generator)
├── Containerfile            # unprivileged nginx serving the HTML
├── nginx.conf               # server block (:8080, headers, gzip, /healthz)
├── deploy/
│   ├── biglabel-k8s.yaml    # Namespace + Deployment (2 replicas) + Service + Ingress
│   └── deploy.sh            # build → push GHCR → rollout
└── README.md
```

> **Filename:** the uploaded file is currently `Bigabel.html` (missing an 'l').
> Rename it to `Biglabel.html` on commit, or adjust the `COPY` in the Containerfile.

## Deploy

```
# first time: create namespace + copy the GHCR pull secret (private image)
kubectl create namespace biglabel
kubectl -n trace get secret ghcr-pull -o yaml \
  | sed 's/namespace: trace/namespace: biglabel/' | kubectl -n biglabel apply -f -

./biglabel/deploy/deploy.sh v0.1.0
```

(Or make the GHCR package public — it holds only a public HTML page — and drop
`imagePullSecrets` from the manifest.)

## TLS & Cloudflare

The Ingress ships on `letsencrypt-staging` (HTTP-01), the cluster's current
mechanism. Confirm staging, flip to `letsencrypt-prod`, and issue once with
`cmctl renew biglabel-tls -n biglabel` — **never delete the cert secret**
(DEPLOYMENT §5/§7).

`saidtheape.com` is a Cloudflare zone, so put this behind the edge with the
existing pattern: add `saidtheape.com  biglabel.saidtheape.com` to
`platform/cloudflare/proxied-hosts.conf`, then
`CF_API_TOKEN=... ./platform/cloudflare/cf-onboard.sh biglabel.saidtheape.com`.
Once the DNS-01 cutover lands, switch this Ingress's issuer to
`letsencrypt-dns01-prod` (platform/cloudflare/, DECISIONS 2026-06-06).

## Hardening (already applied) + next steps

Applied: runs as **non-root** (unprivileged nginx, uid 101, port 8080),
`readOnlyRootFilesystem`, all Linux capabilities dropped, `seccomp:
RuntimeDefault`, two replicas anti-affined across nodes, tight resource caps.

Two optional follow-ups, both genuine improvements for a public site:
- **Vendor the CDN libraries.** The app loads jsPDF / html2canvas / qrcode from
  cdnjs + jsdelivr at runtime, so it breaks if those are blocked/down and can't
  run under a strict CSP. Copying those three files into the image makes it
  self-contained and unlocks a strict `Content-Security-Policy` in `nginx.conf`.
  *(This edits the app's `<script>` tags — app-lane change.)*
- **Egress restraint** comes free behind Cloudflare + the origin lockdown.

## Tested vs assumed

- **Validated here:** YAML parses; `deploy.sh` is `bash -n` clean; the manifest
  follows the cluster's conventions (GHCR pull secret, Traefik, cert-manager).
- **NOT validated on the cluster** (no access here): that the unprivileged image
  serves under `readOnlyRootFilesystem` with the two tmpfs mounts as written
  (if nginx complains about a temp path, add an `emptyDir` for it), the probes,
  and TLS issuance for the host. Deploy once, watch `rollout status`, load the
  page, and **generate a test PDF** (the real check that the CDN libs loaded)
  before treating it as done.

## Docs to update (app-lane / follow-ups, not done here)

- `RESPONSIBILITY.md`: add a row for `biglabel/` (Application-owned, like Trace).
- `DECISIONS.md`: a short `[zip-game]`-style entry — new static app, hosted on
  nginx (not Flask) because it's client-side-only.
