"""
app.py — Flask server for trace.

Routes:

  Static
    GET  /                              → trace.html

  Meta / discovery
    GET  /api/health                    → backend info
    GET  /api/tos                       → current ToS text + version + FAQ
    GET  /api/summary                   → simple aggregates over all rows

  Users (phase 1)
    POST /api/users                     → create/update profile, accept ToS
    GET  /api/users/<uid>               → fetch profile
    DELETE /api/users/<uid>             → erase user + all their attempts

  Attempts
    POST /api/attempts                  → log one attempt
    GET  /api/attempts?user_id=&limit=  → list attempts

  Leaderboards (phase 2)
    GET  /api/leaderboard/puzzle?seed=&size=&difficulty=
    GET  /api/leaderboard/daily[?date=YYYY-MM-DD]
    GET  /api/daily                     → today's daily puzzle metadata

  Aggregates + insights (phase 3 + 4)
    GET  /api/aggregates[?size=&difficulty=]
    GET  /api/insights/personal/<uid>
    GET  /api/insights?slice_by=&metric=&size=&difficulty=&min_samples=
                                       [&verified_env_only=1]
"""

import os
import traceback
from flask import Flask, request, jsonify, send_file, g

import db as DB


app = Flask(__name__, static_folder=None)


# ─────────────────────────────────────────────────────────────────────────
# Locate the single canonical trace.html.
# ─────────────────────────────────────────────────────────────────────────
# There is exactly ONE client file. It normally lives one directory up from
# this server package (the project root), so the standalone file:// copy and
# the server-served copy are the same file. Resolution order:
#   1. $TRACE_HTML_PATH, if set and present (explicit override)
#   2. ../trace.html      (local dev / repo layout, and the container layout
#                           where /app/trace.html sits above /app/trace-server)
#   3. ./trace.html       (last-ditch fallback if someone drops a copy here)
def _resolve_html_path():
    override = os.environ.get('TRACE_HTML_PATH')
    if override and os.path.isfile(override):
        return os.path.abspath(override)
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.abspath(os.path.join(here, '..', 'trace.html'))
    if os.path.isfile(parent):
        return parent
    local = os.path.join(here, 'trace.html')
    if os.path.isfile(local):
        return local
    raise FileNotFoundError(
        "trace.html not found. Expected it one level up from app.py "
        "(../trace.html), or set TRACE_HTML_PATH to its absolute path."
    )

HTML_PATH = _resolve_html_path()


# ─────────────────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────────────────
# One Database manager per process (per gunicorn worker, created post-fork).
# It owns connections; each request borrows one in before_request and returns
# it in teardown_request. Routes read `g.conn`, `db.backend`, `db.placeholder`.
#
# connect() blocks with retries so the app waits for a not-yet-ready Postgres
# container instead of crash-looping. POSTGRES_CONNECT_RETRIES / _DELAY tune
# how long it waits (default ~60s).
db = DB.Database()
db.connect(
    retries=int(os.environ.get('POSTGRES_CONNECT_RETRIES', '30')),
    delay=float(os.environ.get('POSTGRES_CONNECT_DELAY', '2')),
)
db.init_schema()
print(f"[trace] DB ready: backend={db.backend}, ToS v{DB.CURRENT_TOS_VERSION}")
print(f"[trace] serving client from: {HTML_PATH}")


@app.before_request
def _borrow_conn():
    g.conn = db.borrow()


@app.teardown_request
def _return_conn(exc):
    conn = g.pop('conn', None)
    db.release(conn, failed=exc is not None)


# ─────────────────────────────────────────────────────────────────────────
# Static
# ─────────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    # Single source of truth — see _resolve_html_path() above.
    return send_file(HTML_PATH)


@app.route('/favicon.ico')
def favicon():
    # Return No Content so the browser stops complaining about 404. Drop in
    # an actual favicon next to app.py and switch to send_from_directory if
    # you want a real icon.
    return '', 204


# ─────────────────────────────────────────────────────────────────────────
# Meta
# ─────────────────────────────────────────────────────────────────────────

@app.route('/api/health')
def health():
    return jsonify({
        'ok': True,
        'backend': db.backend,
        'tos_version': DB.CURRENT_TOS_VERSION,
    })


# Placeholder ToS + FAQ text. Bump CURRENT_TOS_VERSION in db.py when you
# change anything material here; existing users will be re-prompted.
TOS_TEXT = """Trace is a puzzle game that records your attempts so you can \
track your performance over time and contribute to anonymous aggregate \
statistics about how environmental and lifestyle factors affect puzzle solving.

By using Trace, you agree:

  • An anonymous identifier (a random UUID) will be generated in your browser \
    and stored locally. We never collect your email, name, or any directly-\
    identifying information.

  • Basic play data — puzzle seed, size, difficulty, your time, move counts — \
    may be included in anonymous aggregate statistics.

  • Optional lifestyle data (meals, sleep, stimulants, etc.) is held back from \
    both public display AND aggregate statistics unless you explicitly opt in.

  • You can change your preferences or erase all your data at any time from \
    the Settings panel."""

FAQ_ITEMS = [
    {
        "q": "What data do you collect?",
        "a": "Times, moves, and backtracks for every solved puzzle. Optionally, "
             "if you enable it, your location, current weather, sunrise/sunset, "
             "and self-reported lifestyle context (last meal, sleep, etc.). "
             "Everything is keyed to an anonymous UUID generated in your browser."
    },
    {
        "q": "Will I be identified?",
        "a": "No. Your anonymous UUID is only known to your browser. We never "
             "collect email, real name, or any other directly-identifying info. "
             "Your display name (if you set one) is purely cosmetic and only "
             "shown alongside your puzzle times if you opted in."
    },
    {
        "q": "How is my data anonymised in aggregate statistics?",
        "a": "Aggregate statistics (medians, percentiles, slice insights) report "
             "numbers computed across many users, not individuals. Group results "
             "with fewer than 20 contributors are suppressed entirely so single "
             "attempts can't be back-traced to a person. Your lifestyle data is "
             "excluded from aggregates entirely unless you specifically opt in."
    },
    {
        "q": "Can I opt out of aggregates without giving up the game?",
        "a": "Yes. Your lifestyle data is held back by default. You can also "
             "make every attempt private (excluded from public leaderboards) "
             "from Settings. Basic anonymous play data flows into aggregate "
             "counts under the Terms — that's what the per-puzzle leaderboards "
             "are computed from."
    },
    {
        "q": "Can I delete my data?",
        "a": "Yes. The Settings panel has 'Erase all my data' which clears "
             "both your local copy AND your server-side record."
    },
]


@app.route('/api/tos')
def tos():
    return jsonify({
        'version': DB.CURRENT_TOS_VERSION,
        'text': TOS_TEXT,
        'faq': FAQ_ITEMS,
    })


@app.route('/api/summary')
def get_summary():
    return jsonify(DB.summary(g.conn, db.backend))


# ─────────────────────────────────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────────────────────────────────

@app.route('/api/users', methods=['POST'])
def post_user():
    """Create or update a user profile (incl. accepting current ToS)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON body required'}), 400
    try:
        row = DB.upsert_user(g.conn, db.backend, db.placeholder, data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception:
        traceback.print_exc()
        return jsonify({'error': 'internal error'}), 500
    return jsonify(row)


@app.route('/api/users/<user_id>', methods=['GET'])
def get_user_route(user_id):
    row = DB.get_user(g.conn, db.backend, db.placeholder, user_id)
    if row is None:
        return jsonify({'error': 'not found'}), 404
    return jsonify(row)


@app.route('/api/users/<user_id>', methods=['DELETE'])
def delete_user_route(user_id):
    """GDPR-style erasure of one user's data."""
    deleted = DB.delete_user_data(g.conn, db.backend, db.placeholder, user_id)
    return jsonify({'deleted_attempts': deleted})


# ─────────────────────────────────────────────────────────────────────────
# Attempts
# ─────────────────────────────────────────────────────────────────────────

@app.route('/api/attempts', methods=['POST'])
def post_attempt():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON body required'}), 400

    # Refuse attempts from users who haven't accepted current ToS.
    # This is the server's enforcement of the play gate — the client
    # also blocks at the UI level, but defence in depth matters.
    user = DB.get_user(g.conn, db.backend, db.placeholder, data.get('user_id', ''))
    if user is None:
        return jsonify({
            'error': 'user not registered — POST /api/users first',
            'tos_version': DB.CURRENT_TOS_VERSION,
        }), 403
    if user['tos_version'] < DB.CURRENT_TOS_VERSION:
        return jsonify({
            'error': 'ToS version out of date',
            'current_tos_version': DB.CURRENT_TOS_VERSION,
            'your_tos_version': user['tos_version'],
        }), 403

    try:
        new_id = DB.insert_attempt(g.conn, db.backend, db.placeholder, data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception:
        traceback.print_exc()
        return jsonify({'error': 'internal error'}), 500
    return jsonify({'id': new_id}), 201


@app.route('/api/attempts', methods=['GET'])
def get_attempts():
    user_id = request.args.get('user_id')
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
    except (TypeError, ValueError):
        limit = 50
    rows = DB.list_attempts(g.conn, db.backend, db.placeholder,
                            user_id=user_id, limit=limit)
    return jsonify(rows)


# ─────────────────────────────────────────────────────────────────────────
# Leaderboards (phase 2)
# ─────────────────────────────────────────────────────────────────────────

@app.route('/api/leaderboard/puzzle')
def leaderboard_puzzle_route():
    seed = request.args.get('seed')
    try:
        size = int(request.args.get('size'))
    except (TypeError, ValueError):
        return jsonify({'error': 'size required (int)'}), 400
    difficulty = request.args.get('difficulty')
    if not (seed and difficulty):
        return jsonify({'error': 'seed and difficulty required'}), 400
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
    except (TypeError, ValueError):
        limit = 50
    rows = DB.leaderboard_puzzle(g.conn, db.backend, db.placeholder,
                                 seed, size, difficulty, limit)
    return jsonify({
        'seed': seed, 'size': size, 'difficulty': difficulty,
        'rows': rows
    })


@app.route('/api/leaderboard/daily')
def leaderboard_daily_route():
    date_str = request.args.get('date')
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
    except (TypeError, ValueError):
        limit = 50
    return jsonify(
        DB.leaderboard_daily(g.conn, db.backend, db.placeholder, date_str, limit)
    )


@app.route('/api/daily')
def daily_route():
    """Today's daily puzzle metadata (without leaderboard rows)."""
    date_str = request.args.get('date')
    daily = DB.get_or_create_daily(g.conn, db.backend, db.placeholder, date_str)
    return jsonify(daily)


# ─────────────────────────────────────────────────────────────────────────
# Aggregates + insights (phase 3 + 4)
# ─────────────────────────────────────────────────────────────────────────

@app.route('/api/aggregates')
def aggregates_route():
    """Global medians/percentiles, optionally filtered to a (size, diff)."""
    try:
        size = request.args.get('size', type=int)
        difficulty = request.args.get('difficulty')
    except (TypeError, ValueError):
        return jsonify({'error': 'bad size'}), 400
    return jsonify(DB.global_aggregates(
        g.conn, db.backend, db.placeholder, size, difficulty
    ))


@app.route('/api/insights/personal/<user_id>')
def insights_personal_route(user_id):
    return jsonify(DB.personal_insights(g.conn, db.backend, db.placeholder, user_id))


@app.route('/api/insights')
def insights_slice_route():
    slice_by = request.args.get('slice_by')
    metric = request.args.get('metric', 'median_ms')
    size = request.args.get('size', type=int)
    difficulty = request.args.get('difficulty')
    min_samples = request.args.get('min_samples', default=20, type=int)
    verified_env_only = request.args.get('verified_env_only') in ('1', 'true', 'yes')

    if not slice_by:
        return jsonify({'error': 'slice_by required'}), 400
    if min_samples < 1:
        return jsonify({'error': 'min_samples must be ≥ 1'}), 400

    try:
        return jsonify(DB.insights_slice(
            g.conn, db.backend, db.placeholder,
            slice_by=slice_by, metric=metric,
            size=size, difficulty=difficulty,
            min_samples=min_samples, verified_env_only=verified_env_only,
        ))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


# ─────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
