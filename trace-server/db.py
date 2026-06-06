"""
db.py — thin data-access layer for the trace server.

This module hides three things from callers:

  1. Backend selection (sqlite / postgres) — chosen from DATABASE_URL.
  2. Backend differences:
       • parameter style: SQLite uses "?", psycopg2 uses "%s"
       • AUTOINCREMENT vs SERIAL primary keys
       • lastrowid vs RETURNING for the id of a newly-inserted row
       • row factories — both backends are normalised to dict-like rows
  3. Schema migrations — adds missing columns from earlier versions.

Why hand-rolled instead of SQLAlchemy?
  • Two backends, one table family, a handful of queries — an ORM is more
    abstraction than this earns.
  • Every SQL statement is right there in the code, easy to read.

Connection handling: the Database class (below) owns connections. For SQLite
it keeps one long-lived connection (WAL mode). For Postgres it keeps a small
per-process pool, validates connections on borrow, and discards poisoned ones
on return — so the app survives the Postgres container starting late or
restarting under it. Callers borrow a connection per request and pass it to
the free functions, which are unchanged and backend-agnostic.

Privacy filtering happens here too. Aggregate / leaderboard queries JOIN
users and filter by the relevant consent flag (is_public,
share_lifestyle_in_aggregate, share_lifestyle_publicly) so privacy is
enforced at the data layer, not just in the API.
"""

import os
import sqlite3
import time
import datetime
from urllib.parse import urlparse


# ═════════════════════════════════════════════════════════════════════════
# Constants
# ═════════════════════════════════════════════════════════════════════════

# Bump this whenever the ToS / FAQ text in /api/tos changes meaningfully.
# Users who accepted an older version will be re-prompted on next load.
CURRENT_TOS_VERSION = 1

# Columns clients may set when POSTing an attempt. The full schema has more
# (id, created_at) which are server-managed and excluded here.
ALLOWED_ATTEMPT_COLUMNS = {
    'user_id', 'seed', 'size', 'difficulty',
    'started_at', 'completed_at', 'duration_ms',
    'moves', 'backtracks', 'undos', 'clears', 'solved', 'cheated',
    'is_public', 'env_verified', 'tos_version', 'client_version',
    'latitude', 'longitude', 'location_label',
    'local_time_iso', 'sunrise_iso', 'sunset_iso',
    'weather_temp_c', 'weather_condition', 'weather_wind_kmh',
    'last_meal_at', 'last_meal_desc',
    'last_stimulant_at', 'last_stimulant_desc', 'last_stimulant_amount',
    'last_intoxicant_at', 'last_intoxicant_desc', 'last_intoxicant_amount',
    'last_exercise_at', 'last_exercise_desc', 'last_exercise_amount',
    'woke_at', 'slept_at',
    'sleep_quality_desc', 'sleep_quality_amount',
}

REQUIRED_ATTEMPT_COLUMNS = {'user_id', 'seed', 'size', 'difficulty', 'started_at'}

# Columns clients may set when POSTing a user profile.
ALLOWED_USER_COLUMNS = {
    'user_id', 'display_name',
    'public_by_default',
    'share_lifestyle_publicly',
    'share_lifestyle_in_aggregate',
    'tos_version',
}

# Lifestyle / self-report columns — used by the insights slicer to know
# which columns require the share_lifestyle_in_aggregate consent flag.
# Environmental fields (location, weather) DON'T require this — they're
# auto-detected, not personal-history disclosures, and are covered by
# basic ToS acceptance.
LIFESTYLE_COLUMNS = {
    'last_meal_at', 'last_meal_desc',
    'last_stimulant_at', 'last_stimulant_desc', 'last_stimulant_amount',
    'last_intoxicant_at', 'last_intoxicant_desc', 'last_intoxicant_amount',
    'last_exercise_at', 'last_exercise_desc', 'last_exercise_amount',
    'woke_at', 'slept_at',
    'sleep_quality_desc', 'sleep_quality_amount',
}

# Columns the insights slicer is allowed to slice by — superset of lifestyle
# plus environmental fields. Anything else is rejected (no slicing by
# duration_ms, no slicing by user_id, etc.)
SLICEABLE_COLUMNS = LIFESTYLE_COLUMNS | {
    'weather_condition', 'location_label',
    # Derived (computed in SQL) — not real columns but handled specially
    'hour_of_day', 'day_of_week',
}


# ═════════════════════════════════════════════════════════════════════════
# Connection
# ═════════════════════════════════════════════════════════════════════════

def _resolve_url():
    """
    Decide the database URL, in priority order:

      1. $DATABASE_URL — explicit override (local dev, tests, power users).
         You own the escaping if you use this.

      2. Postgres component vars — if $POSTGRES_HOST is set, assemble the URL
         from POSTGRES_{HOST,PORT,USER,PASSWORD,DB}, percent-encoding the
         credentials in code so ANY password works without hand-escaping it
         into a URL. This is what the k8s deployment uses, and it's why the
         Secret can hold a raw password with @ : / [ ] # etc. safely.

      3. sqlite:///trace.db — the local default.

    Why this exists: a hand-written DATABASE_URL with a special character in
    the password (e.g. a '[') makes urlparse raise "Invalid IPv6 URL" and the
    app never starts. Assembling + encoding here removes that footgun.
    """
    explicit = os.environ.get('DATABASE_URL')
    if explicit:
        return explicit

    host = os.environ.get('POSTGRES_HOST')
    if host:
        from urllib.parse import quote
        # safe='' encodes everything that isn't unreserved, so the resulting
        # URL is always parseable; libpq percent-decodes it back to the
        # original credentials when it connects.
        user = quote(os.environ.get('POSTGRES_USER', 'trace'), safe='')
        password = quote(os.environ.get('POSTGRES_PASSWORD', ''), safe='')
        dbname = quote(os.environ.get('POSTGRES_DB', 'trace'), safe='')
        port = os.environ.get('POSTGRES_PORT', '5432')
        return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

    return 'sqlite:///trace.db'


def _pg_connect_kwargs():
    """
    Build discrete psycopg2/libpq connection parameters for Postgres.

    This is the robust path: the password is handed to libpq as a literal
    keyword argument, NOT embedded in a postgresql:// URI. That matters
    because a URI requires the password to be percent-encoded and then
    percent-DECODED by libpq, and that decode is a place where characters like
    '&' or '^' can go wrong across libpq versions. Passing discrete params
    skips URI parsing entirely — the password travels verbatim, exactly like
    the PGPASSWORD environment variable does.

    Preference order mirrors _resolve_url():
      1. POSTGRES_* component vars (what the k8s deployment sets) — used as-is.
      2. An explicit DATABASE_URL — parsed into parts, percent-DECODING any
         escapes the user put in it, so we still end up with literal values.
    """
    host = os.environ.get('POSTGRES_HOST')
    if host:
        return {
            'host': host,
            'port': int(os.environ.get('POSTGRES_PORT', '5432')),
            'user': os.environ.get('POSTGRES_USER', 'trace'),
            'password': os.environ.get('POSTGRES_PASSWORD', ''),
            'dbname': os.environ.get('POSTGRES_DB', 'trace'),
        }
    from urllib.parse import urlparse, unquote
    p = urlparse(os.environ.get('DATABASE_URL', ''))
    kw = {}
    if p.hostname: kw['host'] = p.hostname
    if p.port:     kw['port'] = p.port
    if p.username: kw['user'] = unquote(p.username)
    if p.password: kw['password'] = unquote(p.password)
    dbname = (p.path or '').lstrip('/')
    if dbname:     kw['dbname'] = unquote(dbname)
    return kw


def open_db():
    """
    Open a connection based on DATABASE_URL. Returns (conn, backend, placeholder)
    where backend is 'sqlite' or 'postgres' and placeholder is '?' or '%s'.
    """
    url = _resolve_url()
    parsed = urlparse(url)

    if parsed.scheme == 'sqlite':
        path = parsed.path
        if path.startswith('/'):
            path = path[1:]
        if not path:
            path = 'trace.db'
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        # WAL lets readers and a writer coexist without blocking each other,
        # and busy_timeout makes a writer wait (up to 5s) for a lock instead
        # of failing immediately with "database is locked". Together these
        # make SQLite tolerate multiple gunicorn workers in one container.
        conn.execute('PRAGMA journal_mode = WAL')
        conn.execute('PRAGMA busy_timeout = 5000')
        conn.execute('PRAGMA synchronous = NORMAL')
        return conn, 'sqlite', '?'

    if parsed.scheme in ('postgres', 'postgresql'):
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError as e:
            raise RuntimeError(
                "DATABASE_URL is a Postgres URL but psycopg2 is not installed. "
                "Add psycopg2-binary to your requirements (see requirements.txt)."
            ) from e
        # Connect with discrete params (not the URI) so the password is never
        # percent-decoded by libpq — see _pg_connect_kwargs().
        conn = psycopg2.connect(**_pg_connect_kwargs())
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        return conn, 'postgres', '%s'

    raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme!r}")


def cursor(conn, backend):
    """Backend-agnostic cursor factory yielding dict-style rows.

    For Postgres, the connection's own cursor_factory is set to RealDictCursor
    (in open_db / Database.borrow), so a plain conn.cursor() already yields
    dict rows.
    """
    return conn.cursor()


# ═════════════════════════════════════════════════════════════════════════
# Database — connection manager (the thing app.py actually holds)
# ═════════════════════════════════════════════════════════════════════════
# Owns connections so individual requests don't have to. Two backends, two
# strategies:
#
#   SQLite   — one long-lived connection in WAL mode, shared within the
#              process. borrow() hands it out, release() is a no-op. (Each
#              gunicorn worker is its own process and so has its own.)
#
#   Postgres — a small ThreadedConnectionPool per process. borrow() checks a
#              connection is alive (cheap SELECT 1) before handing it out and
#              recycles it if not; release() rolls back any leftover
#              transaction state and returns it to the pool, or discards it if
#              the request errored. This is what lets the app tolerate the
#              dedicated Postgres container starting after it or restarting
#              underneath it.
#
# connect() blocks with retries at startup so the app waits for Postgres to
# accept connections rather than crash-looping.
# ═════════════════════════════════════════════════════════════════════════

class Database:
    def __init__(self, url=None):
        self.url = url or _resolve_url()
        scheme = urlparse(self.url).scheme
        if scheme == 'sqlite':
            self.backend = 'sqlite'
            self.placeholder = '?'
        elif scheme in ('postgres', 'postgresql'):
            self.backend = 'postgres'
            self.placeholder = '%s'
        else:
            raise ValueError(f"Unsupported DATABASE_URL scheme: {scheme!r}")
        self._sqlite_conn = None
        self._pool = None
        # Discrete connection params for Postgres (avoids URI password decode).
        self._pg_kwargs = _pg_connect_kwargs() if self.backend == 'postgres' else None

    # ── Startup ────────────────────────────────────────────────────────────
    def connect(self, retries=30, delay=2.0, minconn=1, maxconn=5):
        """
        Establish the SQLite connection or build the Postgres pool. For
        Postgres, retry up to `retries` times (delay seconds apart) so the app
        tolerates the database container not being ready yet.
        """
        if self.backend == 'sqlite':
            # Reuse open_db()'s SQLite setup (WAL, busy_timeout, etc.).
            self._sqlite_conn, _, _ = open_db()
            return

        import psycopg2
        from psycopg2.pool import ThreadedConnectionPool
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                # Build the pool from discrete params (host/user/password/...),
                # NOT a dsn URI — keeps the password literal for libpq.
                self._pool = ThreadedConnectionPool(minconn, maxconn, **self._pg_kwargs)
                # Prove it actually works, not just that the pool object built.
                conn = self._pool.getconn()
                try:
                    with conn.cursor() as c:
                        c.execute('SELECT 1')
                finally:
                    self._pool.putconn(conn)
                print(f"[trace] connected to Postgres (attempt {attempt})")
                return
            except Exception as e:  # psycopg2.OperationalError and friends
                last_err = e
                if self._pool is not None:
                    try: self._pool.closeall()
                    except Exception: pass
                    self._pool = None
                print(f"[trace] Postgres not ready (attempt {attempt}/{retries}): {e}")
                time.sleep(delay)
        raise RuntimeError(
            f"Could not connect to Postgres after {retries} attempts: {last_err}"
        )

    # ── Per-request borrow / return ──────────────────────────────────────────
    def _alive(self, conn):
        try:
            with conn.cursor() as c:
                c.execute('SELECT 1')
            return True
        except Exception:
            return False

    def borrow(self):
        """Get a connection to use for one request."""
        if self.backend == 'sqlite':
            return self._sqlite_conn
        import psycopg2.extras
        conn = self._pool.getconn()
        if not self._alive(conn):
            # Stale (e.g. Postgres restarted while this conn sat idle in the
            # pool). Drop it and grab a fresh one.
            try: self._pool.putconn(conn, close=True)
            except Exception: pass
            conn = self._pool.getconn()
        # Make every cursor from this connection yield dict-style rows, which
        # is what the DAL's dict(row) expects. cursor_factory is a writable
        # attribute on psycopg2 connections.
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        return conn

    def release(self, conn, failed=False):
        """Return a connection after a request."""
        if self.backend == 'sqlite':
            return  # keep the shared WAL connection alive
        if conn is None:
            return
        if failed:
            try: self._pool.putconn(conn, close=True)
            except Exception: pass
            return
        try:
            # Clear any leftover/aborted transaction state before reuse. The
            # DAL commits its own writes, so this only discards uncommitted
            # reads — never committed data.
            conn.rollback()
            self._pool.putconn(conn)
        except Exception:
            try: self._pool.putconn(conn, close=True)
            except Exception: pass

    # ── Schema ───────────────────────────────────────────────────────────────
    def init_schema(self):
        conn = self.borrow()
        try:
            init_schema(conn, self.backend)
        finally:
            self.release(conn)

    def close(self):
        if self.backend == 'sqlite' and self._sqlite_conn is not None:
            try: self._sqlite_conn.close()
            except Exception: pass
        elif self._pool is not None:
            try: self._pool.closeall()
            except Exception: pass


# ═════════════════════════════════════════════════════════════════════════
# Schema bootstrap + migration
# ═════════════════════════════════════════════════════════════════════════

# Columns we might need to ADD to an existing v1 attempts table. Each entry
# is (column_name, column_type_for_sqlite, column_type_for_postgres). When
# init_schema runs, we try each ADD and ignore the "duplicate column" error
# that fires if it's already there.
ATTEMPTS_V2_COLUMNS = [
    ('is_public',    'INTEGER NOT NULL DEFAULT 0', 'INTEGER NOT NULL DEFAULT 0'),
    ('env_verified', 'INTEGER NOT NULL DEFAULT 0', 'INTEGER NOT NULL DEFAULT 0'),
    ('tos_version',  'INTEGER NOT NULL DEFAULT 1', 'INTEGER NOT NULL DEFAULT 1'),
    ('cheated',      'INTEGER NOT NULL DEFAULT 0', 'INTEGER NOT NULL DEFAULT 0'),
    ('client_version', 'TEXT', 'TEXT'),
]

def init_schema(conn, backend, schema_path=None):
    """
    Apply schema.sql and run additive migrations.
    Idempotent — safe to call on every server start.

    schema_path defaults to schema.sql sitting next to this module, so it
    works regardless of the process's current working directory (important
    under gunicorn / in a container).
    """
    if schema_path is None:
        schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')
    with open(schema_path) as f:
        sql = f.read()

    if backend == 'postgres':
        # 1) Autoincrement PK → SERIAL.
        sql = sql.replace(
            'INTEGER PRIMARY KEY AUTOINCREMENT',
            'SERIAL PRIMARY KEY'
        )
        # 2) Remaining INTEGER columns → BIGINT. Several columns store unix
        #    timestamps in milliseconds (~1.7e12), which overflow Postgres's
        #    32-bit INTEGER (max ~2.1e9). SQLite's INTEGER is variable-width so
        #    it never shows there, but Postgres raises "integer out of range".
        #    BIGINT is a safe superset for every integer column we have, so a
        #    blanket swap (after the SERIAL rewrite above) is correct.
        sql = sql.replace(' INTEGER', ' BIGINT')

    cur = cursor(conn, backend)
    if backend == 'sqlite':
        cur.executescript(sql)
    else:
        cur.execute(sql)
    conn.commit()
    cur.close()

    # Additive migrations: try to add v2 columns to attempts. The CREATE TABLE
    # above already includes them for fresh installs; this catches existing
    # v1 databases.
    for col_name, sqlite_type, pg_type in ATTEMPTS_V2_COLUMNS:
        col_type = pg_type if backend == 'postgres' else sqlite_type
        cur = cursor(conn, backend)
        try:
            cur.execute(f"ALTER TABLE attempts ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except Exception:
            # Column probably already exists. Both backends throw on duplicate.
            conn.rollback()
        finally:
            cur.close()

    # Seed editable UI text (welcome banners, consent card copy, ToS, FAQ) on
    # a fresh database. No-op once any rows exist, so direct admin edits stand.
    seed_ui_text(conn, backend)


# ═════════════════════════════════════════════════════════════════════════
# Editable UI text  (welcome banners, consent card copy, ToS body, FAQ)
# ═════════════════════════════════════════════════════════════════════════
# These defaults are the seed for a fresh database only. Once the table has
# rows, an admin edits them directly in the database (and, later, via an admin
# UI) — seeding never overwrites them. The client also carries its own copy of
# this text as an offline/file:// fallback.

DEFAULT_WELCOME_BANNERS = [
    "Boring stuff first:",
    "And now for something completely normal:",
    "Wait, it gets worse:",
    "A short moment of tedium before the fun stuff:",
    "Dull but worthy bit:",
    "Some choices. Why? Because, OK?",
    "Sorry for a minor reality intrusion:",
    "Fun, excitement and really wild things. After this period of enforced boredom:",
    "Excitement denied! Choose your GDPR options first!",
    "Ah. Ts & Cs. How lovely:",
    "But first! Let's spend some heartbeats on data protection.",
]

# Order here is the on-screen order; keys match data-uitext hooks in the client.
DEFAULT_CONSENT_CARD = [
    ('eyebrow',          'Welcome'),
    ('title',            'Before you play'),
    ('intro',            'Trace records your puzzle attempts so you can track how you do '
                         'over time and contribute to anonymous aggregate statistics. We '
                         'never collect your email or name — just an anonymous random ID '
                         'held in your browser.'),
    ('name_label',       'Display name (optional)'),
    ('name_placeholder', 'e.g. PathFinder42'),
    ('accept_h',         'I accept the Terms above'),
    ('accept_d',         'Required to play. Lets us count your basic play stats (times, '
                         'moves) in anonymous aggregates.'),
    ('public_h',         'Show me on public leaderboards'),
    ('public_d',         'Your display name and times appear on per-puzzle and '
                         'daily-challenge leaderboards. You can override per-attempt.'),
    ('lifestyle_pub_h',  'Allow my lifestyle data to be shown publicly'),
    ('lifestyle_pub_d',  'Things like "last meal", "stimulants", "sleep" can appear '
                         'alongside your display name. Off by default.'),
    ('lifestyle_agg_h',  'Include my lifestyle data in anonymous aggregates'),
    ('lifestyle_agg_d',  'Lets queries like "median time when caffeinated" include your '
                         'data, with at least 20 contributors before any group is shown. '
                         'Your identity is never attached.'),
    ('continue_button',  'Continue'),
    ('banner_ok_button', 'OK'),
]

DEFAULT_TOS_BODY = (
    "Trace is a puzzle game that records your attempts so you can track your "
    "performance over time and contribute to anonymous aggregate statistics "
    "about how environmental and lifestyle factors affect puzzle solving.\n\n"
    "By using Trace, you agree:\n\n"
    "  • An anonymous identifier (a random UUID) will be generated in your "
    "browser and stored locally. We never collect your email, name, or any "
    "directly-identifying information.\n\n"
    "  • Basic play data — puzzle seed, size, difficulty, your time, move "
    "counts — may be included in anonymous aggregate statistics.\n\n"
    "  • Optional lifestyle data (meals, sleep, stimulants, etc.) is held back "
    "from both public display AND aggregate statistics unless you explicitly "
    "opt in.\n\n"
    "  • You can change your preferences or erase all your data at any time "
    "from the Settings panel."
)

DEFAULT_FAQ = [
    ("What data do you collect?",
     "Times, moves, and backtracks for every solved puzzle. Optionally, if you "
     "enable it, your location, current weather, sunrise/sunset, and "
     "self-reported lifestyle context (last meal, sleep, etc.). Everything is "
     "keyed to an anonymous UUID generated in your browser."),
    ("Will I be identified?",
     "No. Your anonymous UUID is only known to your browser. We never collect "
     "email, real name, or any other directly-identifying info. Your display "
     "name (if you set one) is purely cosmetic and only shown alongside your "
     "puzzle times if you opted in."),
    ("How is my data anonymised in aggregate statistics?",
     "Aggregate statistics (medians, percentiles, slice insights) report "
     "numbers computed across many users, not individuals. Group results with "
     "fewer than 20 contributors are suppressed entirely so single attempts "
     "can't be back-traced to a person. Your lifestyle data is excluded from "
     "aggregates entirely unless you specifically opt in."),
    ("Can I opt out of aggregates without giving up the game?",
     "Yes. Your lifestyle data is held back by default. You can also make "
     "every attempt private (excluded from public leaderboards) from Settings. "
     "Basic anonymous play data flows into aggregate counts under the Terms — "
     "that's what the per-puzzle leaderboards are computed from."),
    ("Can I delete my data?",
     "Yes. The Settings panel has 'Erase all my data' which clears both your "
     "local copy AND your server-side record."),
]


def seed_ui_text(conn, backend):
    """Insert default UI text if the table is empty. Idempotent."""
    ph = '%s' if backend == 'postgres' else '?'
    cur = cursor(conn, backend)
    cur.execute("SELECT COUNT(*) AS n FROM ui_text")
    row = cur.fetchone()
    count = (row['n'] if isinstance(row, dict) or hasattr(row, 'keys') else row[0])
    cur.close()
    if count and int(count) > 0:
        return  # already populated (possibly admin-edited) — leave it alone

    now = int(time.time() * 1000)
    rows = []
    for i, phrase in enumerate(DEFAULT_WELCOME_BANNERS):
        rows.append(('welcome_banner', None, phrase, i))
    for i, (key, val) in enumerate(DEFAULT_CONSENT_CARD):
        rows.append(('consent_card', key, val, i))
    rows.append(('tos', 'body', DEFAULT_TOS_BODY, 0))
    for i, (q, a) in enumerate(DEFAULT_FAQ):
        rows.append(('faq', q, a, i))

    cur = cursor(conn, backend)
    for category, text_key, body, sort_order in rows:
        cur.execute(
            f"INSERT INTO ui_text (category, text_key, body, sort_order, active, updated_at) "
            f"VALUES ({ph}, {ph}, {ph}, {ph}, 1, {ph})",
            (category, text_key, body, sort_order, now)
        )
    conn.commit()
    cur.close()


def get_ui_text(conn, backend):
    """
    Return every active UI-text row in ONE query, ordered for display. The
    caller (the /api/ui-text route) groups these into banners / card / tos /
    faq; the random welcome-banner choice is made client-side.
    """
    cur = cursor(conn, backend)
    cur.execute(
        "SELECT category, text_key, body, sort_order FROM ui_text "
        "WHERE active = 1 ORDER BY category, sort_order, id"
    )
    out = [dict(r) for r in cur.fetchall()]
    cur.close()
    return out

def get_user(conn, backend, placeholder, user_id):
    """Returns the user row as a dict, or None if not found."""
    cur = cursor(conn, backend)
    cur.execute(f"SELECT * FROM users WHERE user_id = {placeholder}", (user_id,))
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None


def upsert_user(conn, backend, placeholder, data):
    """
    Create or update a user. `data` must include user_id; other keys are
    optional and filtered against ALLOWED_USER_COLUMNS.

    On INSERT: tos_accepted_at is required. On UPDATE: it's not touched.
    Returns the resulting user row.
    """
    user_id = data.get('user_id')
    if not user_id:
        raise ValueError("user_id required")

    existing = get_user(conn, backend, placeholder, user_id)
    now = int(time.time() * 1000)

    # Filter incoming data to whitelist
    clean = {k: v for k, v in data.items() if k in ALLOWED_USER_COLUMNS}

    if existing is None:
        # New user — must include ToS acceptance signal
        if 'tos_version' not in clean:
            raise ValueError("tos_version required for new users (ToS acceptance)")
        row = {
            'user_id': user_id,
            'display_name': clean.get('display_name'),
            'tos_accepted_at': now,
            'tos_version': clean.get('tos_version', CURRENT_TOS_VERSION),
            'public_by_default': int(clean.get('public_by_default', 0)),
            'share_lifestyle_publicly': int(clean.get('share_lifestyle_publicly', 0)),
            'share_lifestyle_in_aggregate': int(clean.get('share_lifestyle_in_aggregate', 0)),
            'created_at': now,
            'updated_at': now,
        }
        keys = list(row.keys())
        placeholders = ', '.join([placeholder] * len(keys))
        cur = cursor(conn, backend)
        cur.execute(
            f"INSERT INTO users ({', '.join(keys)}) VALUES ({placeholders})",
            [row[k] for k in keys]
        )
        conn.commit()
        cur.close()
        return row

    # Existing user — UPDATE the columns provided
    # tos_accepted_at gets re-set if tos_version goes up (re-acceptance)
    update_cols = {}
    for k in ('display_name', 'public_by_default',
              'share_lifestyle_publicly', 'share_lifestyle_in_aggregate'):
        if k in clean:
            update_cols[k] = (int(clean[k]) if k != 'display_name' else clean[k])

    if 'tos_version' in clean and clean['tos_version'] > existing['tos_version']:
        update_cols['tos_version'] = clean['tos_version']
        update_cols['tos_accepted_at'] = now

    update_cols['updated_at'] = now

    if update_cols:
        set_clause = ', '.join(f"{k} = {placeholder}" for k in update_cols.keys())
        values = list(update_cols.values()) + [user_id]
        cur = cursor(conn, backend)
        cur.execute(
            f"UPDATE users SET {set_clause} WHERE user_id = {placeholder}",
            values
        )
        conn.commit()
        cur.close()

    return get_user(conn, backend, placeholder, user_id)


def delete_user_data(conn, backend, placeholder, user_id):
    """
    GDPR-style erasure: delete user row and all their attempts. Returns the
    count of attempts deleted.
    """
    cur = cursor(conn, backend)
    cur.execute(f"DELETE FROM attempts WHERE user_id = {placeholder}", (user_id,))
    attempts_deleted = cur.rowcount
    cur.execute(f"DELETE FROM users WHERE user_id = {placeholder}", (user_id,))
    conn.commit()
    cur.close()
    return attempts_deleted


# ═════════════════════════════════════════════════════════════════════════
# Attempts
# ═════════════════════════════════════════════════════════════════════════

def insert_attempt(conn, backend, placeholder, data):
    """
    Insert an attempt. Auto-resolves is_public from the user's
    public_by_default if not explicitly set.
    """
    missing = REQUIRED_ATTEMPT_COLUMNS - set(data.keys())
    if missing:
        raise ValueError(f"Missing required fields: {sorted(missing)}")

    clean = {k: v for k, v in data.items() if k in ALLOWED_ATTEMPT_COLUMNS}

    # client_version is untrusted free text supplied by the client — stored for
    # troubleshooting/error correlation only, never read back into any logic.
    # Coerce to a bounded string so a malformed or hostile client can't write an
    # oversized blob. (The parameterised INSERT already neutralises injection.)
    if clean.get('client_version') is not None:
        clean['client_version'] = str(clean['client_version'])[:64]

    # If is_public wasn't sent, default from the user's profile.
    if 'is_public' not in clean:
        user = get_user(conn, backend, placeholder, clean['user_id'])
        clean['is_public'] = int(user['public_by_default']) if user else 0

    # Mark env_verified if any environmental field is non-null
    if 'env_verified' not in clean:
        env_fields = ('latitude', 'longitude', 'weather_temp_c')
        clean['env_verified'] = 1 if any(clean.get(f) is not None for f in env_fields) else 0

    clean['created_at'] = int(time.time() * 1000)

    keys = list(clean.keys())
    placeholders = ', '.join([placeholder] * len(keys))
    cols = ', '.join(keys)
    values = [clean[k] for k in keys]

    cur = cursor(conn, backend)
    if backend == 'postgres':
        cur.execute(
            f"INSERT INTO attempts ({cols}) VALUES ({placeholders}) RETURNING id",
            values,
        )
        new_id = cur.fetchone()['id']
    else:
        cur.execute(
            f"INSERT INTO attempts ({cols}) VALUES ({placeholders})",
            values,
        )
        new_id = cur.lastrowid
    conn.commit()
    cur.close()
    return new_id


def list_attempts(conn, backend, placeholder, user_id=None, limit=50):
    """List recent attempts, optionally filtered to one user."""
    cur = cursor(conn, backend)
    if user_id is None:
        cur.execute(
            f"SELECT * FROM attempts ORDER BY started_at DESC LIMIT {placeholder}",
            (limit,),
        )
    else:
        cur.execute(
            f"SELECT * FROM attempts WHERE user_id = {placeholder} "
            f"ORDER BY started_at DESC LIMIT {placeholder}",
            (user_id, limit),
        )
    rows = cur.fetchall()
    cur.close()
    return [dict(r) for r in rows]


def summary(conn, backend):
    """High-level counts across all stored attempts."""
    cur = cursor(conn, backend)
    cur.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(solved) AS solved,
            CAST(AVG(CASE WHEN solved=1 THEN duration_ms END) AS INTEGER) AS avg_ms,
            AVG(CASE WHEN solved=1 THEN backtracks END) AS avg_backtracks
        FROM attempts
    """)
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else {'total': 0, 'solved': 0, 'avg_ms': 0, 'avg_backtracks': None}


# ═════════════════════════════════════════════════════════════════════════
# Daily puzzles (phase 2)
# ═════════════════════════════════════════════════════════════════════════

# How daily puzzles are picked: a rotation over (size, difficulty) bands
# that cycles through the week, so users see variety. The seed for each
# day is the date string itself, so anyone can independently regenerate
# the same puzzle from that day without server help.
#
# Day-of-week (Mon=0..Sun=6) → (size, difficulty)
DAILY_ROTATION = {
    0: (6, 'tricky'),    # Mon
    1: (6, 'knotty'),    # Tue
    2: (7, 'tricky'),    # Wed
    3: (7, 'knotty'),    # Thu
    4: (6, 'fiendish'),  # Fri
    5: (7, 'fiendish'),  # Sat
    6: (8, 'tricky'),    # Sun — gentler kickoff for weekend
}

def derive_daily(date_str):
    """Return (seed, size, difficulty) for a given YYYY-MM-DD."""
    d = datetime.date.fromisoformat(date_str)
    size, difficulty = DAILY_ROTATION[d.weekday()]
    return (date_str, size, difficulty)


def get_or_create_daily(conn, backend, placeholder, date_str=None):
    """
    Return the daily puzzle for a date (default today UTC). Creates the
    row on first access.
    """
    if date_str is None:
        date_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')

    cur = cursor(conn, backend)
    cur.execute(f"SELECT * FROM daily_puzzles WHERE date = {placeholder}", (date_str,))
    row = cur.fetchone()
    cur.close()
    if row:
        return dict(row)

    seed, size, difficulty = derive_daily(date_str)
    now = int(time.time() * 1000)
    cur = cursor(conn, backend)
    try:
        cur.execute(
            f"INSERT INTO daily_puzzles (date, seed, size, difficulty, created_at) "
            f"VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})",
            (date_str, seed, size, difficulty, now)
        )
        conn.commit()
    except Exception:
        # Race condition — another request inserted first. Re-read.
        conn.rollback()
    finally:
        cur.close()

    cur = cursor(conn, backend)
    cur.execute(f"SELECT * FROM daily_puzzles WHERE date = {placeholder}", (date_str,))
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None


# ═════════════════════════════════════════════════════════════════════════
# Leaderboards (phase 2)
# ═════════════════════════════════════════════════════════════════════════

# For per-puzzle and per-day leaderboards, we want the user's BEST attempt
# (fastest solve), not all attempts. Several attempts per user-puzzle are
# common — they might solve again on a different device, or replay.
#
# The query: for each user with a solved attempt on this puzzle, take their
# fastest duration. JOIN to users for display_name. Filter by is_public AND
# solved.

def leaderboard_puzzle(conn, backend, placeholder, seed, size, difficulty, limit=50):
    """
    Top times for one specific puzzle. Only public solved attempts.
    Returns one row per user (their personal best on this puzzle).
    """
    cur = cursor(conn, backend)
    cur.execute(f"""
        SELECT
            u.display_name,
            a.user_id,
            MIN(a.duration_ms) AS best_ms,
            MIN(a.moves)       AS best_moves,
            MIN(a.backtracks)  AS best_backtracks,
            COUNT(*)           AS attempt_count,
            MAX(a.created_at)  AS last_attempt_at
        FROM attempts a
        JOIN users u ON u.user_id = a.user_id
        WHERE a.seed = {placeholder}
          AND a.size = {placeholder}
          AND a.difficulty = {placeholder}
          AND a.solved = 1
          AND a.is_public = 1
          AND a.cheated = 0
        GROUP BY a.user_id, u.display_name
        ORDER BY best_ms ASC
        LIMIT {placeholder}
    """, (seed, size, difficulty, limit))
    rows = cur.fetchall()
    cur.close()
    return [dict(r) for r in rows]


def leaderboard_daily(conn, backend, placeholder, date_str=None, limit=50):
    """
    Today's daily puzzle leaderboard. Returns the daily puzzle metadata
    plus the leaderboard rows.
    """
    daily = get_or_create_daily(conn, backend, placeholder, date_str)
    if daily is None:
        return {'puzzle': None, 'rows': []}
    rows = leaderboard_puzzle(
        conn, backend, placeholder,
        daily['seed'], daily['size'], daily['difficulty'], limit
    )
    return {'puzzle': daily, 'rows': rows}


# ═════════════════════════════════════════════════════════════════════════
# Global aggregates + personal insights (phase 3)
# ═════════════════════════════════════════════════════════════════════════

def global_aggregates(conn, backend, placeholder, size=None, difficulty=None):
    """
    Median/mean times and counts, optionally filtered to one (size, difficulty).
    SQLite doesn't have a native MEDIAN function — we compute approximate
    percentiles in Python after pulling the durations. For low volume this
    is fine; for high volume, swap to a streaming-quantile approach or use
    Postgres's percentile_cont.

    Includes only public solved attempts so the numbers match what users
    can verify on the per-puzzle leaderboards.
    """
    where_parts = ["solved = 1", "is_public = 1", "cheated = 0"]
    params = []
    if size is not None:
        where_parts.append(f"size = {placeholder}")
        params.append(size)
    if difficulty is not None:
        where_parts.append(f"difficulty = {placeholder}")
        params.append(difficulty)
    where = " AND ".join(where_parts)

    cur = cursor(conn, backend)
    cur.execute(f"""
        SELECT duration_ms, moves, backtracks
        FROM attempts
        WHERE {where}
        ORDER BY duration_ms ASC
    """, params)
    rows = cur.fetchall()
    cur.close()

    durations = [r['duration_ms'] for r in rows if r['duration_ms']]
    if not durations:
        return {
            'count': 0, 'median_ms': None, 'p25_ms': None, 'p75_ms': None,
            'fastest_ms': None, 'slowest_ms': None,
            'mean_moves': None, 'mean_backtracks': None,
        }

    n = len(durations)
    def pct(p):
        # nearest-rank percentile, conservative for small N
        idx = max(0, min(n - 1, int(round((p / 100.0) * (n - 1)))))
        return durations[idx]

    moves = [r['moves'] for r in rows if r['moves'] is not None]
    bts = [r['backtracks'] for r in rows if r['backtracks'] is not None]

    return {
        'count': n,
        'median_ms': pct(50),
        'p25_ms': pct(25),
        'p75_ms': pct(75),
        'fastest_ms': durations[0],
        'slowest_ms': durations[-1],
        'mean_moves': round(sum(moves) / len(moves), 1) if moves else None,
        'mean_backtracks': round(sum(bts) / len(bts), 2) if bts else None,
    }


def personal_insights(conn, backend, placeholder, user_id):
    """
    Bring back a user's own attempts grouped by useful slices so they can
    see "their best time when X". Returns a structured summary.

    Note: uses the user's OWN data only, not aggregates. Doesn't require
    share_lifestyle_in_aggregate — they're looking at themselves.
    """
    cur = cursor(conn, backend)
    cur.execute(f"""
        SELECT * FROM attempts
        WHERE user_id = {placeholder} AND solved = 1
        ORDER BY started_at DESC
    """, (user_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()

    if not rows:
        return {'total_solved': 0, 'slices': {}}

    # Slices we compute by default
    slice_cols = [
        'difficulty', 'size',
        'sleep_quality_desc', 'last_stimulant_desc',
        'weather_condition',
    ]
    slices = {}
    for col in slice_cols:
        groups = {}
        for r in rows:
            key = r.get(col)
            if key is None or key == '':
                continue
            groups.setdefault(key, []).append(r['duration_ms'])
        if not groups:
            continue
        slices[col] = {
            k: {
                'count': len(v),
                'median_ms': sorted(v)[len(v) // 2] if v else None,
                'best_ms': min(v) if v else None,
            }
            for k, v in groups.items()
        }

    return {
        'total_solved': len(rows),
        'slices': slices,
    }


# ═════════════════════════════════════════════════════════════════════════
# General insights slicer (phase 4)
# ═════════════════════════════════════════════════════════════════════════
#
# THE distinctive endpoint: ask any sliceable column × any metric, with a
# minimum-samples guard so single attempts can't masquerade as insights.
#
# Critical privacy filter: any slice over a LIFESTYLE_COLUMN only includes
# attempts from users who set share_lifestyle_in_aggregate = 1. Environmental
# slices (weather, location) don't need that flag — they're covered by
# basic ToS acceptance.
#
# Examples:
#   slice_by=last_stimulant_desc, metric=median_ms, size=6, difficulty=tricky
#   → { "coffee": 145000, "tea": 178000, "none": 192000 }
#
#   slice_by=weather_condition, metric=median_ms, difficulty=knotty
#   → { "clear": 187000, "rain": 214000, "partly cloudy": 195000 }

ALLOWED_METRICS = {'median_ms', 'mean_ms', 'best_ms', 'count', 'mean_backtracks'}

def insights_slice(conn, backend, placeholder,
                   slice_by, metric='median_ms',
                   size=None, difficulty=None, min_samples=20,
                   verified_env_only=False):
    """
    Group public solved attempts by `slice_by` column and compute `metric`
    for each group. Drops groups with fewer than min_samples rows.
    """
    if slice_by not in SLICEABLE_COLUMNS:
        raise ValueError(
            f"slice_by must be one of {sorted(SLICEABLE_COLUMNS)}, got {slice_by!r}"
        )
    if metric not in ALLOWED_METRICS:
        raise ValueError(
            f"metric must be one of {sorted(ALLOWED_METRICS)}, got {metric!r}"
        )

    where_parts = [
        "a.solved = 1",
        "a.is_public = 1",
        "a.cheated = 0",
    ]
    params = []

    # Lifestyle slices require the user's consent flag.
    if slice_by in LIFESTYLE_COLUMNS:
        where_parts.append("u.share_lifestyle_in_aggregate = 1")

    if verified_env_only:
        where_parts.append("a.env_verified = 1")

    if size is not None:
        where_parts.append(f"a.size = {placeholder}")
        params.append(size)
    if difficulty is not None:
        where_parts.append(f"a.difficulty = {placeholder}")
        params.append(difficulty)

    # Derived slices need a SQL expression instead of a column name.
    # We use strftime for hour_of_day / day_of_week (SQLite syntax).
    # For Postgres, this would be EXTRACT(...) — but for the PoC
    # the derived slices are SQLite-only; on Postgres they degrade
    # to NULL (and so get filtered out below).
    if slice_by == 'hour_of_day' and backend == 'sqlite':
        slice_expr = "CAST(strftime('%H', a.local_time_iso) AS INTEGER)"
    elif slice_by == 'day_of_week' and backend == 'sqlite':
        slice_expr = "CAST(strftime('%w', a.local_time_iso) AS INTEGER)"
    else:
        slice_expr = f"a.{slice_by}"

    where_parts.append(f"{slice_expr} IS NOT NULL")
    where = " AND ".join(where_parts)

    cur = cursor(conn, backend)
    cur.execute(f"""
        SELECT {slice_expr} AS bucket, a.duration_ms, a.backtracks
        FROM attempts a
        JOIN users u ON u.user_id = a.user_id
        WHERE {where}
        ORDER BY bucket
    """, params)
    rows = cur.fetchall()
    cur.close()

    # Bucket and compute in Python (portable across both backends)
    buckets = {}
    for r in rows:
        b = r['bucket']
        if b == '' or b is None:
            continue
        buckets.setdefault(b, []).append(r)

    results = {}
    for b, group in buckets.items():
        if len(group) < min_samples:
            continue
        durations = sorted([g['duration_ms'] for g in group if g['duration_ms']])
        bts = [g['backtracks'] for g in group if g['backtracks'] is not None]
        if not durations:
            continue
        if metric == 'median_ms':
            results[str(b)] = durations[len(durations) // 2]
        elif metric == 'mean_ms':
            results[str(b)] = int(sum(durations) / len(durations))
        elif metric == 'best_ms':
            results[str(b)] = durations[0]
        elif metric == 'count':
            results[str(b)] = len(durations)
        elif metric == 'mean_backtracks':
            results[str(b)] = round(sum(bts) / len(bts), 2) if bts else None

    return {
        'slice_by': slice_by,
        'metric': metric,
        'min_samples': min_samples,
        'size': size,
        'difficulty': difficulty,
        'verified_env_only': verified_env_only,
        'buckets': results,
        'total_rows_considered': len(rows),
        'buckets_below_threshold': sum(
            1 for g in buckets.values() if len(g) < min_samples
        ),
    }
