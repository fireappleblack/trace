# flatten:begin
# repo-path: trace-server/app.py
# generated: 2026-06-06T16:30:04Z by flatten.py — do not edit this block
# flatten:end

"""
app.py — Flask server for trace.

Routes:

  Static
    GET  /                              → trace.html

  Meta / discovery
    GET  /api/health                    → backend info
    GET  /api/ui-text                   → editable UI text (banners, card, ToS, FAQ) + version
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


# UI text (welcome banners, consent-card copy, ToS body, FAQ) now lives in the
# database (ui_text table), editable without touching app code. Defaults are
# seeded by db.seed_ui_text(). Bump CURRENT_TOS_VERSION in db.py when a ToS
# change is material enough to re-prompt existing users.


@app.route('/api/ui-text')
def ui_text():
    # One query for everything; group it into the shape the client wants. The
    # random welcome-banner choice is made client-side from `welcome_banners`.
    rows = DB.get_ui_text(g.conn, db.backend)
    banners = [r['body'] for r in rows if r['category'] == 'welcome_banner']
    card = {r['text_key']: r['body'] for r in rows if r['category'] == 'consent_card'}
    tos = next((r['body'] for r in rows
                if r['category'] == 'tos' and r['text_key'] == 'body'), '')
    faq = [{'q': r['text_key'], 'a': r['body']} for r in rows if r['category'] == 'faq']
    return jsonify({
        'version': DB.CURRENT_TOS_VERSION,
        'welcome_banners': banners,
        'consent_card': card,
        'tos': tos,
        'faq': faq,
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
