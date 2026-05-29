# Trace — a path-puzzle web app

A LinkedIn-Zip-style path puzzle that records your solving habits and
optionally feeds anonymous aggregate statistics about how environment and
lifestyle affect puzzle performance.

## What's here

- **`trace.html`** — single-file standalone app. Drop it on any web server
  (or open via `file://` — most features work, except those that need a
  server, like leaderboards). Generator, solver, local SQLite-in-browser
  persistence, the lot.

- **`trace-server/`** — Flask app that serves `trace.html` plus a small
  REST API for cross-user leaderboards, aggregates, and insights. SQLite by
  default; switch to Postgres by setting `DATABASE_URL`. See its own README
  for setup.

## Privacy model

Trace requires a one-time consent step before you can play. There are four
controls; only one is required:

| Control                                | Default | Required? |
|----------------------------------------|---------|-----------|
| Accept Terms                           | —       | **Yes** — gates the puzzle |
| Show me on public leaderboards         | Off     | No        |
| Allow lifestyle data to be shown publicly | Off  | No        |
| Include lifestyle data in anonymous aggregates | Off | No   |

Basic play data (times, moves, backtracks) flows into aggregate stats under
the basic Terms acceptance. Lifestyle data (meals, sleep, stimulants) is
held back from both public display AND aggregates unless you explicitly opt
in to each. The two lifestyle toggles are **independent** — you can opt in
to aggregation without making it publicly visible, and vice versa.

Aggregate group results with fewer than 20 contributors are suppressed
entirely. You can erase all your data from the Settings panel at any time.

## What's in each phase

- **Phases 1–2** (earlier) — generator, solver, four difficulty bands,
  seeded sharing.
- **Phase 3** (earlier) — attempt logging with timer/moves/backtracks/undos,
  optional environmental context (location/weather/sun) and self-report
  (meals/sleep/stimulants), local SQLite, optional server sync.
- **Phase 4** (this build) — `users` table, ToS gate, daily challenge,
  per-puzzle / daily / global / personal leaderboards, and the **insights
  slicer**: pick any column × any metric to see "median solve time when
  caffeinated", "best time by sleep quality", etc, with privacy filtering.

## How the insights slicer works

Open Leaderboard → Insights tab. Pick a slice column (e.g. `last_stimulant_desc`)
and a metric (e.g. `median_ms`), optionally narrow by puzzle size or
difficulty, set a minimum-contributors threshold (defaults to 20), and run.
Results are horizontal bar charts ranked by metric. Lifestyle slices include
only attempts from users who opted in to `share_lifestyle_in_aggregate`;
environmental slices (weather, location) are covered by basic consent.
