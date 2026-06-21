-- flatten:begin
-- repo-path: trace-server/schema.sql
-- generated: 2026-06-16T22:17:07Z by flatten.py — do not edit this block
-- flatten:end

-- ─────────────────────────────────────────────────────────────────────────
-- TRACE — server-side schema (v2: adds users, daily_puzzles, consent flags)
-- ─────────────────────────────────────────────────────────────────────────
-- This is the canonical schema for the server's database. It mirrors the
-- one embedded in the single-file app (trace.html, search for "const SCHEMA")
-- so attempts saved locally can be POSTed straight to /api/attempts without
-- field mapping.
--
-- Dialect: SQLite by default. The Python DAL (db.py) rewrites a few keywords
-- when the active backend is Postgres:
--   • "INTEGER PRIMARY KEY AUTOINCREMENT"  →  "SERIAL PRIMARY KEY"
--
-- Migrations: this file uses CREATE TABLE IF NOT EXISTS for everything, and
-- db.py applies safe ALTER TABLE statements after, wrapped in try/except, so
-- existing databases from earlier versions pick up the new columns without
-- erroring on columns they already have.
-- ─────────────────────────────────────────────────────────────────────────


-- ─────────────────────────────────────────────────────────────────────────
-- users — one row per anonymous browser UUID
-- ─────────────────────────────────────────────────────────────────────────
-- Identity is the random UUID generated in the browser. We never collect
-- email, name, or any directly-identifying info. display_name is purely
-- cosmetic and only shown on leaderboards if the user opted in.
--
-- The three consent flags are INDEPENDENT — a user can opt in to any subset:
--   • public_by_default
--       Show display_name on per-puzzle and global leaderboards.
--       When 1, this user's solved attempts default to is_public=1.
--       (Per-attempt override via the log modal is always available.)
--
--   • share_lifestyle_publicly
--       Allow lifestyle/self-report fields (meals, sleep, stimulants, etc.)
--       to be displayed alongside this user's display_name in any public
--       view. When 0, those columns are NEVER shown attached to identity.
--
--   • share_lifestyle_in_aggregate
--       Allow lifestyle fields to be included in anonymous medians /
--       percentiles / slice insights. When 0, this user's lifestyle data
--       is stored locally only (or stored on server but excluded from
--       aggregate queries via JOIN filtering).
--
-- All three default to 0 (maximum privacy). The user opts IN during
-- onboarding or later via Settings.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    user_id                       TEXT PRIMARY KEY,
    display_name                  TEXT,

    -- Terms of Service acceptance — required to play
    tos_accepted_at               INTEGER NOT NULL,
    tos_version                   INTEGER NOT NULL DEFAULT 1,

    -- Three independent opt-in flags
    public_by_default             INTEGER NOT NULL DEFAULT 0,
    share_lifestyle_publicly      INTEGER NOT NULL DEFAULT 0,
    share_lifestyle_in_aggregate  INTEGER NOT NULL DEFAULT 0,

    created_at                    INTEGER NOT NULL,
    updated_at                    INTEGER NOT NULL
);


-- ─────────────────────────────────────────────────────────────────────────
-- daily_puzzles — registry of "puzzle of the day" entries
-- ─────────────────────────────────────────────────────────────────────────
-- One puzzle per date, same for all users worldwide on that date. The
-- server picks them in advance OR computes them deterministically from
-- the date string. For phase 2 we use deterministic derivation (the seed
-- IS the date, plus a configured size/difficulty rotation), so this table
-- is mostly a cache / convenience for fast leaderboard lookups.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_puzzles (
    date         TEXT PRIMARY KEY,  -- 'YYYY-MM-DD' in UTC
    seed         TEXT NOT NULL,
    size         INTEGER NOT NULL,
    difficulty   TEXT NOT NULL,
    created_at   INTEGER NOT NULL
);


-- ─────────────────────────────────────────────────────────────────────────
-- attempts — main fact table
-- ─────────────────────────────────────────────────────────────────────────
-- New columns vs v1:
--   • is_public       — per-attempt override of user's public_by_default
--   • env_verified    — 1 if location/weather actually detected (not skipped)
--                       Used for the "verified env data only" tab on insights.
--   • tos_version     — which ToS version was in force when this was logged
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS attempts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identity (anonymous UUID, FK to users.user_id)
    user_id         TEXT NOT NULL,

    -- Puzzle identity. Together (seed, size, difficulty) names a puzzle.
    seed            TEXT NOT NULL,
    size            INTEGER NOT NULL,
    difficulty      TEXT NOT NULL,

    -- Timestamps (unix milliseconds)
    started_at      INTEGER NOT NULL,
    completed_at    INTEGER,
    duration_ms     INTEGER,

    -- Play counters
    moves           INTEGER NOT NULL DEFAULT 0,
    backtracks      INTEGER NOT NULL DEFAULT 0,
    undos           INTEGER NOT NULL DEFAULT 0,
    clears          INTEGER NOT NULL DEFAULT 0,
    solved          INTEGER NOT NULL DEFAULT 0,  -- 0 or 1
    cheated         INTEGER NOT NULL DEFAULT 0,  -- solution was revealed during the attempt

    -- Visibility / provenance (v2 additions)
    is_public       INTEGER NOT NULL DEFAULT 0,
    env_verified    INTEGER NOT NULL DEFAULT 0,
    tos_version     INTEGER NOT NULL DEFAULT 1,
    client_version  TEXT,                        -- build tag of the client that logged it; untrusted, logged only

    -- Wriggliness scoring (v0.42.0). turns = number of direction changes in the
    -- solved path (the competitive score). board_key is the full board identity
    -- for the new multiple-solutions model — (seed, size, difficulty) no longer
    -- names a board on its own, since mode/wiggle/walls/points/blank also vary.
    -- Both NULL for unsolved attempts or pre-v0.42 clients.
    turns           INTEGER,
    board_key       TEXT,

    -- Environmental context (all optional)
    latitude            REAL,
    longitude           REAL,
    location_label      TEXT,
    local_time_iso      TEXT,
    sunrise_iso         TEXT,
    sunset_iso          TEXT,
    weather_temp_c      REAL,
    weather_condition   TEXT,
    weather_wind_kmh    REAL,

    -- Self-reported state (all optional, all TEXT codes/labels)
    last_meal_at            TEXT,
    last_meal_desc          TEXT,
    last_stimulant_at       TEXT,
    last_stimulant_desc     TEXT,
    last_stimulant_amount   TEXT,
    last_intoxicant_at      TEXT,
    last_intoxicant_desc    TEXT,
    last_intoxicant_amount  TEXT,
    last_exercise_at        TEXT,
    last_exercise_desc      TEXT,
    last_exercise_amount    TEXT,
    woke_at                 TEXT,
    slept_at                TEXT,
    sleep_quality_desc      TEXT,
    sleep_quality_amount    TEXT,

    -- Server-side ingest timestamp (unix ms)
    created_at              INTEGER NOT NULL
);


-- ─────────────────────────────────────────────────────────────────────────
-- Editable UI text
-- ─────────────────────────────────────────────────────────────────────────
-- All player-facing copy that may need changing for legal or design/fun
-- reasons WITHOUT touching app code: the welcome-banner phrases, the
-- data-protection options card copy, the ToS body, and the FAQ. One flat
-- table so the whole lot comes back in a single query
-- (SELECT ... WHERE active = 1 ORDER BY category, sort_order, id).
--
--   category   'welcome_banner' | 'consent_card' | 'tos' | 'faq'
--   text_key   field name for consent_card/tos (e.g. 'title', 'body');
--              the question for faq; NULL for welcome_banner phrases
--   body       the displayed text (for faq rows, the answer)
--   sort_order display / selection order within a category
--   active     0 to retire a row without deleting it
--
-- Seeded with defaults by db.seed_ui_text() only when empty, so editing rows
-- directly in the database (the interim admin method) is never overwritten.
CREATE TABLE IF NOT EXISTS ui_text (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT NOT NULL,
    text_key    TEXT,
    body        TEXT NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1,
    updated_at  INTEGER
);


-- ─────────────────────────────────────────────────────────────────────────
-- Admin accounts (admin v0.2.0) — used ONLY by the separate trace-admin
-- service for multi-admin auth + roles. The public app never reads this table.
-- role is a strict hierarchy: 'cleric' < 'admin' < 'superadmin'
--   cleric     — edit site wording (ui_text)
--   admin      — + game design (find-the-shape, future puzzle/daily config)
--   superadmin — + account/role management (+ audit/logs, deferred)
-- The env-seeded bootstrap superadmin (ADMIN_USERNAME/ADMIN_PASSWORD) is
-- upserted at startup as break-glass; all other accounts live here.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'cleric',
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    INTEGER,
    updated_at    INTEGER,
    last_login_at INTEGER
);


-- ─────────────────────────────────────────────────────────────────────────
-- Indices
-- ─────────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_attempts_user      ON attempts(user_id);
CREATE INDEX IF NOT EXISTS idx_attempts_puzzle    ON attempts(seed, size, difficulty);
CREATE INDEX IF NOT EXISTS idx_attempts_created   ON attempts(created_at);
CREATE INDEX IF NOT EXISTS idx_attempts_public    ON attempts(is_public, solved);
CREATE INDEX IF NOT EXISTS idx_attempts_difficulty ON attempts(size, difficulty, solved);
CREATE INDEX IF NOT EXISTS idx_attempts_wriggle    ON attempts(board_key, solved, is_public);
CREATE INDEX IF NOT EXISTS idx_ui_text_lookup     ON ui_text(active, category, sort_order);
