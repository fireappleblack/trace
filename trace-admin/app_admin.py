# flatten:begin
# repo-path: trace-admin/app_admin.py
# generated: 2026-06-16T22:17:07Z by flatten.py — do not edit this block
# flatten:end

"""
app_admin.py — Flask server for the Trace ADMIN back-end.

This is a SEPARATE service from the public app (trace-server/app.py). The
public app and player client (trace.html) carry NO admin code or admin API
calls. This service shares the game's dedicated Postgres by importing the
SAME data layer (trace-server/db.py) — one source of truth for the schema and
queries — but exposes only admin operations, behind a login.

v1 surface:
  Static
    GET  /                      → admin.html (login shell + UI-text editor)
    GET  /healthz               → liveness (no DB, no auth)
  Auth
    GET  /api/session           → {authenticated, csrf?}
    POST /api/login {password}  → set signed session cookie; returns {csrf}
    POST /api/logout            → clear session
  UI text (admin; all require a valid session + matching CSRF on writes)
    GET    /api/ui-text         → every row (active AND inactive)
    POST   /api/ui-text         → create a row
    PATCH  /api/ui-text/<id>    → patch editable fields
    DELETE /api/ui-text/<id>    → delete a row

Find-the-shape tooling is phase 2 (see Docs/DECISIONS.md) and will be added as
a second module here; it is deliberately not stubbed yet.

Auth model (right-sized for ONE admin):
  - ADMIN_PASSWORD (plain, injected via the --from-env-file secret pattern) is
    hashed at startup; OR ADMIN_PASSWORD_HASH (a pre-computed werkzeug hash) is
    used directly. One of the two MUST be set or the app refuses to start.
  - ADMIN_SECRET_KEY signs the session cookie (HttpOnly, Secure, SameSite=Strict).
  - A per-session CSRF token must be echoed in X-CSRF-Token on every mutation.
  - Login attempts are rate-limited per client IP.
Network exposure (locked-down public subdomain) and edge auth are handled in
deploy/admin-k8s.yaml + the infra lane — see README.md.
"""

import os
import sys
import time
import secrets as _secrets
from functools import wraps
from hmac import compare_digest

from flask import Flask, request, jsonify, send_file, g, session, abort
from werkzeug.security import generate_password_hash, check_password_hash

# ── Import the shared data layer from trace-server (one source of truth) ──
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'trace-server'))
import db as DB  # noqa: E402

ADMIN_HTML_PATH = os.path.join(HERE, 'admin.html')

# ── Bootstrap (break-glass) superadmin credential (fail closed if unset) ──
# The env credential seeds/refreshes ONE god account at startup; all other
# accounts live in admin_users and manage their own passwords.
_BOOTSTRAP_USER = (os.environ.get('ADMIN_USERNAME') or 'root').strip()
_BOOTSTRAP_HASH = os.environ.get('ADMIN_PASSWORD_HASH')
if not _BOOTSTRAP_HASH:
    _pw = os.environ.get('ADMIN_PASSWORD')
    if _pw:
        _BOOTSTRAP_HASH = generate_password_hash(_pw)
if not _BOOTSTRAP_HASH:
    raise RuntimeError(
        'Set ADMIN_PASSWORD (or ADMIN_PASSWORD_HASH) — the admin service will '
        'not start without a bootstrap superadmin credential.'
    )

_SECRET_KEY = os.environ.get('ADMIN_SECRET_KEY')
if not _SECRET_KEY:
    raise RuntimeError('Set ADMIN_SECRET_KEY — needed to sign the session cookie.')

# Strict role hierarchy: a higher rank can do everything a lower one can.
ROLES = {'cleric': 1, 'admin': 2, 'superadmin': 3}

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=_SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE='Strict',
    SESSION_COOKIE_NAME='trace_admin',
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,  # 8h
)

# ── Shared Postgres, same connection lifecycle as the public app ──
db = DB.Database()
db.connect(
    retries=int(os.environ.get('POSTGRES_CONNECT_RETRIES', '30')),
    delay=float(os.environ.get('POSTGRES_CONNECT_DELAY', '2')),
)
db.init_schema()

# Seed/refresh the break-glass superadmin from the env secret (idempotent).
_boot = db.borrow()
try:
    DB.admin_ensure_bootstrap(_boot, db.backend, db.placeholder, _BOOTSTRAP_USER, _BOOTSTRAP_HASH)
finally:
    db.release(_boot)
print(f"[trace-admin] DB ready: backend={db.backend}; bootstrap superadmin={_BOOTSTRAP_USER!r}")


@app.before_request
def _borrow_conn():
    # /healthz must not depend on the DB (it's the liveness probe).
    if request.path == '/healthz':
        return
    g.conn = db.borrow()


@app.teardown_request
def _return_conn(exc):
    conn = g.pop('conn', None)
    if conn is not None:
        db.release(conn, failed=exc is not None)


@app.after_request
def _security_headers(resp):
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Referrer-Policy'] = 'no-referrer'
    # Self-contained single-file client; inline style/script need 'unsafe-inline'.
    resp.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'",
    )
    return resp


# ── Login rate limiting (simple in-memory; fine for a single small replica) ──
_FAILS = {}  # ip -> [count, locked_until_epoch]
_MAX_FAILS = 8
_LOCK_SECONDS = 300


def _client_ip():
    # Behind Traefik/Cloudflare; take the first hop of X-Forwarded-For if present.
    xff = request.headers.get('X-Forwarded-For', '')
    return (xff.split(',')[0].strip() if xff else request.remote_addr) or 'unknown'


def _locked(ip):
    rec = _FAILS.get(ip)
    return bool(rec and rec[1] > time.time())


def _note_fail(ip):
    rec = _FAILS.get(ip) or [0, 0]
    rec[0] += 1
    if rec[0] >= _MAX_FAILS:
        rec[1] = time.time() + _LOCK_SECONDS
        rec[0] = 0
    _FAILS[ip] = rec


def _clear_fail(ip):
    _FAILS.pop(ip, None)


# ── Auth helpers ──
def current_rank():
    return ROLES.get(session.get('role'), 0) if session.get('admin') else 0

def require_rank(min_role):
    """Gate a route at a minimum role in the hierarchy (cleric<admin<superadmin)."""
    need = ROLES[min_role]
    def deco(fn):
        @wraps(fn)
        def _wrap(*a, **kw):
            if not session.get('admin'):
                abort(401)
            if current_rank() < need:
                abort(403)
            return fn(*a, **kw)
        return _wrap
    return deco


def check_csrf():
    sent = request.headers.get('X-CSRF-Token', '')
    have = session.get('csrf', '')
    if not have or not compare_digest(sent, have):
        abort(403)


# ── Static ──
@app.route('/')
def index():
    return send_file(ADMIN_HTML_PATH)


@app.route('/healthz')
def healthz():
    return jsonify({'ok': True})


# ── Auth ──
@app.route('/api/session')
def session_state():
    if session.get('admin'):
        return jsonify({'authenticated': True, 'username': session.get('username'),
                        'role': session.get('role'), 'csrf': session.get('csrf')})
    return jsonify({'authenticated': False})


@app.route('/api/login', methods=['POST'])
def login():
    ip = _client_ip()
    if _locked(ip):
        return jsonify({'error': 'too many attempts; try again later'}), 429
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password', '')
    user = DB.admin_get_user_by_username(g.conn, db.backend, db.placeholder, username) if username else None
    if (not user or not user['active'] or not password
            or not check_password_hash(user['password_hash'], password)):
        _note_fail(ip)
        return jsonify({'error': 'invalid credentials'}), 401
    _clear_fail(ip)
    DB.admin_touch_login(g.conn, db.backend, db.placeholder, user['id'])
    session.clear()
    session['admin'] = True
    session['admin_id'] = user['id']
    session['username'] = user['username']
    session['role'] = user['role']
    session['csrf'] = _secrets.token_urlsafe(32)
    session.permanent = True
    return jsonify({'ok': True, 'username': user['username'], 'role': user['role'], 'csrf': session['csrf']})


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})


# ── My account (any authenticated admin) ──
@app.route('/api/me/password', methods=['POST'])
@require_rank('cleric')
def change_my_password():
    check_csrf()
    data = request.get_json(silent=True) or {}
    cur_pw = data.get('current', '')
    new_pw = data.get('new', '')
    if not new_pw or len(new_pw) < 8:
        return jsonify({'error': 'new password must be at least 8 characters'}), 400
    me = DB.admin_get_user_by_username(g.conn, db.backend, db.placeholder, session.get('username'))
    if not me or not check_password_hash(me['password_hash'], cur_pw):
        return jsonify({'error': 'current password is incorrect'}), 403
    DB.admin_set_user_password(g.conn, db.backend, db.placeholder, me['id'], generate_password_hash(new_pw))
    return jsonify({'ok': True})


# ── Account management (superadmin only) ──
def _guard_last_superadmin(target):
    """Raise 409 if the change would remove the last active superadmin."""
    if target and target['role'] == 'superadmin' and target['active'] \
            and DB.admin_count_active_superadmins(g.conn, db.backend) <= 1:
        abort(409)

@app.route('/api/admins')
@require_rank('superadmin')
def admins_list():
    return jsonify({'rows': DB.admin_list_users(g.conn, db.backend), 'roles': list(ROLES.keys())})

@app.route('/api/admins', methods=['POST'])
@require_rank('superadmin')
def admins_create():
    check_csrf()
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password', '')
    role = data.get('role', 'cleric')
    if not username or not password or len(password) < 8:
        return jsonify({'error': 'username and a password of 8+ characters are required'}), 400
    if role not in ROLES:
        return jsonify({'error': 'invalid role'}), 400
    try:
        new_id = DB.admin_create_user(g.conn, db.backend, db.placeholder, username,
                                      generate_password_hash(password), role)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'id': new_id}), 201

@app.route('/api/admins/<int:uid>', methods=['PATCH'])
@require_rank('superadmin')
def admins_update(uid):
    check_csrf()
    data = request.get_json(silent=True) or {}
    target = DB.admin_get_user(g.conn, db.backend, db.placeholder, uid)
    if not target:
        return jsonify({'error': 'not found'}), 404
    # Demoting or deactivating the last active superadmin would lock everyone out.
    if 'role' in data and data['role'] != 'superadmin':
        _guard_last_superadmin(target)
    if 'active' in data and not data['active']:
        _guard_last_superadmin(target)
    if 'role' in data:
        if data['role'] not in ROLES:
            return jsonify({'error': 'invalid role'}), 400
        DB.admin_set_user_role(g.conn, db.backend, db.placeholder, uid, data['role'])
    if 'active' in data:
        DB.admin_set_user_active(g.conn, db.backend, db.placeholder, uid, bool(data['active']))
    return jsonify({'ok': True})

@app.route('/api/admins/<int:uid>/password', methods=['POST'])
@require_rank('superadmin')
def admins_set_password(uid):
    check_csrf()
    data = request.get_json(silent=True) or {}
    new_pw = data.get('password', '')
    if not new_pw or len(new_pw) < 8:
        return jsonify({'error': 'password must be at least 8 characters'}), 400
    if not DB.admin_get_user(g.conn, db.backend, db.placeholder, uid):
        return jsonify({'error': 'not found'}), 404
    DB.admin_set_user_password(g.conn, db.backend, db.placeholder, uid, generate_password_hash(new_pw))
    return jsonify({'ok': True})

@app.route('/api/admins/<int:uid>', methods=['DELETE'])
@require_rank('superadmin')
def admins_delete(uid):
    check_csrf()
    target = DB.admin_get_user(g.conn, db.backend, db.placeholder, uid)
    if not target:
        return jsonify({'error': 'not found'}), 404
    _guard_last_superadmin(target)
    DB.admin_delete_user(g.conn, db.backend, db.placeholder, uid)
    return jsonify({'ok': True})


# ── UI text CRUD (cleric and up — "alter wording on the site") ──
@app.route('/api/ui-text')
@require_rank('cleric')
def ui_text_list():
    return jsonify({'rows': DB.admin_list_ui_text(g.conn, db.backend)})


@app.route('/api/ui-text', methods=['POST'])
@require_rank('cleric')
def ui_text_create():
    check_csrf()
    data = request.get_json(silent=True) or {}
    try:
        new_id = DB.admin_create_ui_text(g.conn, db.backend, db.placeholder, data)
    except (ValueError, TypeError) as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'id': new_id}), 201


@app.route('/api/ui-text/<int:row_id>', methods=['PATCH'])
@require_rank('cleric')
def ui_text_update(row_id):
    check_csrf()
    data = request.get_json(silent=True) or {}
    try:
        n = DB.admin_update_ui_text(g.conn, db.backend, db.placeholder, row_id, data)
    except (ValueError, TypeError) as e:
        return jsonify({'error': str(e)}), 400
    if not n:
        return jsonify({'error': 'not found or nothing to update'}), 404
    return jsonify({'updated': n})


@app.route('/api/ui-text/<int:row_id>', methods=['DELETE'])
@require_rank('cleric')
def ui_text_delete(row_id):
    check_csrf()
    n = DB.admin_delete_ui_text(g.conn, db.backend, db.placeholder, row_id)
    if not n:
        return jsonify({'error': 'not found'}), 404
    return jsonify({'deleted': n})


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', '5001')), debug=False)
