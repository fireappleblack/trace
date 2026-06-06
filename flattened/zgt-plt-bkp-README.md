<!-- flatten:begin
     repo-path: platform/backups/README.md
     generated: 2026-06-06T16:30:04Z by flatten.py — do not edit this block
flatten:end -->

# Cluster backups (platform)

Off-cluster logical backups of every database → Oracle Object Storage, plus a
complementary Longhorn (block-level) backup target to the same bucket. This is
the **highest-priority** resilience item from `DECISIONS.md` / `STATUS.md` §4
#1, deliberately built **before** stacking more stateful services on the
cluster.

## Why this exists

Longhorn `replicas-2` protects against **node loss**. It does **not** protect
against a bad migration, logical corruption, or an accidental
`delete pvc`/namespace — any of which loses everything. These backups close
that gap. Two layers:

| Layer | What | Saves you from |
|-------|------|----------------|
| **Logical dumps** (`backups.yaml`) | `pg_dump` + per-DB `mariadb-dump`, gzipped, to Object Storage nightly | bad migrations, accidental DROP/DELETE, restoring into a fresh engine |
| **Longhorn target** (`longhorn-backup-target.yaml`) | block-level volume backups to the same bucket | fast whole-volume recovery |

Logical dumps are primary. They're portable and restore into a clean engine.

## Layout

```
platform/backups/
├── Containerfile               # tools-only image (pg+mariadb clients, rclone)
├── backup.sh                   # dump+upload logic (shipped as a ConfigMap)
├── backups.yaml                # namespace + nightly CronJob
├── restore.sh                  # break-glass / tested-restore helper
├── longhorn-backup-target.yaml # block-level layer (Longhorn Settings)
├── apply-backups.sh            # out-of-band secret + ConfigMap setup
└── _secrets_env.example        # OCI S3 creds template (copy → .secrets.env)
```

## Install

```
# 1. Build & push the tools image (once, and when tools change):
podman build -f platform/backups/Containerfile \
  -t ghcr.io/fireappleblack/cluster-backup:v0.1.0 platform/backups
echo $CR_PAT | podman login ghcr.io -u fireappleblack --password-stdin
podman push ghcr.io/fireappleblack/cluster-backup:v0.1.0

# 2. Credentials + deploy:
cp platform/backups/_secrets_env.example platform/backups/.secrets.env
# edit .secrets.env (OCI S3 keys, endpoint, region, bucket)
./platform/backups/apply-backups.sh
```

`apply-backups.sh` derives the **Postgres password from the live `trace-db`
secret** (single source of truth) and the **MariaDB root password from the
`mariadb-root` secret if it exists**. Pre-MariaDB it backs up Postgres only and
tells you so — re-run it after MariaDB lands to start covering MariaDB. No
password is ever passed through the shell or committed.

## First run + the mandated test restore

Don't wait for 02:07 UTC — prove it immediately:

```
kubectl -n platform-backups create job --from=cronjob/db-backup db-backup-manual
kubectl -n platform-backups logs -f job/db-backup-manual
```

Then **test a restore** (the decision requires one). Restore into a scratch DB,
never over the live one:

```
./platform/backups/restore.sh list postgres
# create a scratch db, then:
./platform/backups/restore.sh postgres trace-<stamp>.sql.gz trace_restore_test
```

A backup you've never restored is a guess. Treat the first green restore as the
point at which backups are "real".

## Schedule, retention, cost

- **Schedule:** nightly `7 2 * * *` (UTC). Change in `backups.yaml`.
- **Retention:** `RETENTION_DAYS=30` — `backup.sh` prunes older objects per
  prefix. Belt-and-braces; a **bucket lifecycle rule** in OCI is the cleaner
  primary retention mechanism (set it on the bucket and you can lower or drop
  the script-side prune).
- **Concurrency:** `Forbid` + `startingDeadlineSeconds` — no overlap, no
  catch-up storm after downtime.
- Dumps are gzipped at `-9`. For a hobby cluster this is pennies in Object
  Storage.

## Restore (break-glass)

`restore.sh` runs a transient in-cluster pod that reuses the backup secrets:

```
./platform/backups/restore.sh list mariadb
./platform/backups/restore.sh postgres <object> <target_db>
./platform/backups/restore.sh mariadb  <object>
```

MariaDB dumps are **per-database** (`--databases <db>`), so each WordPress site
restores independently.

## Tested vs assumed (be honest)

- **Validated here:** YAML parses; shell parses (`bash -n`); the manifest
  follows the cluster's established conventions (out-of-band secrets, GHCR pull
  secret, Longhorn).
- **NOT yet validated against the live cluster** (no cluster access from where
  this was written): the OCI S3-compat endpoint/keys, that `rclone rcat`
  uploads succeed against your bucket, the cross-namespace DB connectivity, and
  the restore. **You must run the manual job + a test restore** before trusting
  this — same staging-first discipline as TLS.
- **Assumptions to confirm:** bucket exists and is private; region is
  `uk-london-1` (edit if not); the `trace-db` secret key is `POSTGRES_PASSWORD`
  and (later) the MariaDB secret key is `MARIADB_ROOT_PASSWORD`.
