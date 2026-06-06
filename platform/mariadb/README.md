# Shared MariaDB (platform)

One MariaDB engine, a database + least-privilege user **per tenant**
(WordPress site). Platform-owned shared infrastructure — distinct from the zip
game's dedicated Postgres, which stays app-owned (`RESPONSIBILITY.md`).

WordPress requires MySQL/MariaDB; one shared engine is far kinder to the 12 GB
nodes than one engine per site (`DECISIONS.md` 2026-05-31 [platform]
"WordPress: pod-per-site, shared MariaDB"). Capacity target: ~10–20 low-traffic
sites alongside the zip game and mail.

## Install

```
cp platform/mariadb/_secrets_env.example platform/mariadb/.secrets.env
# edit .secrets.env — set MARIADB_ROOT_PASSWORD
./platform/mariadb/apply-mariadb.sh
```

Then **re-run the backups helper** so MariaDB starts being backed up:

```
./platform/backups/apply-backups.sh
```

Per-site DBs/users are created by `wordpress/apply-site.sh`, not here.

## Tuning — what's folded in and where it deviates

Translated from the generic baseline (`DECISIONS.md` 2026-05-31 [cross-cutting]
"Postgres/MariaDB tuning baseline") into `mariadb-tuning` (a ConfigMap mounted
at `/etc/mysql/conf.d/zz-tuning.cnf`):

| Baseline (generic) | MariaDB here | Why |
|--------------------|--------------|-----|
| `shared_buffers` 32–64M | `innodb_buffer_pool_size = 256M` | Buffer pool is the InnoDB analog; 256M caches many small WP DBs and is the first knob to raise if busy. Bounded by the 768Mi container limit. |
| `work_mem` 4M | small per-connection buffers (`sort`/`join` 1M, `read` 256K, `tmp_table` 16M) | Per-connection RAM is what actually scales with load — kept small so 60 connections stay cheap. |
| `max_connections` 20–30 | `max_connections = 60` | **Deliberate deviation:** the baseline was for a *dedicated* DB. A *shared* engine behind 10–20 sites would hit "Too many connections" at 30. Logged in `DECISIONS.md`. Keep per-site php-fpm worker counts modest to stay under it. |

Memory limit (768Mi) ≈ buffer pool + per-connection buffers + overhead, so the
engine's footprint is bounded while mail + WP + the zip game coexist.

To change tuning: edit `mariadb.yaml`'s ConfigMap, `kubectl apply`, then
restart the pod (`kubectl -n mariadb rollout restart statefulset/mariadb`).
Config changes need a restart.

## Ops

| Task | Command |
|------|---------|
| Shell into MariaDB | `kubectl -n mariadb exec -it statefulset/mariadb -- mariadb -uroot -p` |
| List site DBs | `… -e 'SHOW DATABASES;'` |
| Storage health | `kubectl -n longhorn-system get volumes.longhorn.io` |
| Restart (after tuning change) | `kubectl -n mariadb rollout restart statefulset/mariadb` |

## Gotchas

- **Root password drift** (same as Postgres, `DEPLOYMENT.md` §7): the password
  is baked at first init on the PVC. Changing the Secret later does **not**
  change the password MariaDB already has — rotate inside MariaDB too. Never
  edit the Secret alone on an initialised volume.
- **`storageClassName: longhorn` is explicit** on the PVC — never rely on the
  cluster default (k3s re-marks `local-path` default on upgrade).
- **Data lives under `subPath: mariadb`** on the volume, keeping it clear of the
  volume root's `lost+found`.

## Tested vs assumed

- **Validated:** YAML parses; shell parses; follows cluster conventions.
- **NOT validated on the live cluster** (no cluster access here): that
  `mariadb:11.4`'s `healthcheck.sh` probe passes as written, that the tuning
  file is picked up, and real connection load. Apply it, watch
  `rollout status`, and shell in to confirm `SHOW VARIABLES LIKE
  'innodb_buffer_pool_size'` reflects the ConfigMap before trusting it.
