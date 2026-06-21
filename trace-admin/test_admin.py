# flatten:begin
# repo-path: trace-admin/test_admin.py
# generated: 2026-06-16T22:17:07Z by flatten.py — do not edit this block
# flatten:end

import os, tempfile
os.environ['DATABASE_URL'] = 'sqlite:///' + tempfile.mktemp(suffix='.db')
os.environ['ADMIN_PASSWORD'] = 'root-correct-horse'      # bootstrap superadmin pw
os.environ['ADMIN_SECRET_KEY'] = 'test-signing-key'
# ADMIN_USERNAME unset → bootstrap superadmin is 'root'

import app_admin
app_admin.app.config['SESSION_COOKIE_SECURE'] = False    # test client uses http
app_admin.app.config['TESTING'] = True
APP = app_admin.app

ok=0; n=0
def chk(c, m):
    global ok,n; n+=1; print(('PASS' if c else 'FAIL'),'-',m); ok+=1 if c else 0

def login(user, pw, ip='1.1.1.1'):
    c = APP.test_client()
    r = c.post('/api/login', json={'username':user,'password':pw}, environ_overrides={'REMOTE_ADDR':ip})
    return c, r

# ── anonymous ──
anon = APP.test_client()
chk(anon.get('/api/session').get_json()=={'authenticated':False}, 'anon: not authenticated')
chk(anon.get('/api/ui-text').status_code==401, 'anon: ui-text 401')
chk(anon.get('/api/admins').status_code==401, 'anon: admins 401')
chk(anon.get('/healthz').get_json()['ok'], 'healthz ok (no auth)')
chk(anon.post('/api/login', json={'username':'root','password':'nope'}).status_code==401, 'wrong password 401')
chk(anon.post('/api/login', json={'username':'ghost','password':'x'}).status_code==401, 'unknown user 401')

# ── bootstrap superadmin ──
su, r = login('root', 'root-correct-horse')
chk(r.status_code==200 and r.get_json()['role']=='superadmin', 'bootstrap root logs in as superadmin')
csrf = r.get_json()['csrf']
s = su.get('/api/session').get_json()
chk(s['authenticated'] and s['username']=='root' and s['role']=='superadmin', 'session reports username+role')
H = {'X-CSRF-Token': csrf}

# superadmin can see ui-text and admins
chk(su.get('/api/ui-text').status_code==200, 'superadmin: ui-text 200')
al = su.get('/api/admins'); chk(al.status_code==200, 'superadmin: admins 200')
chk(any(u['username']=='root' and u['role']=='superadmin' for u in al.get_json()['rows']), 'root listed as superadmin')

# ── create accounts ──
chk(su.post('/api/admins', json={'username':'cleo','password':'clericpass1','role':'cleric'}, headers=H).status_code==201, 'create cleric')
chk(su.post('/api/admins', json={'username':'amy','password':'adminpass12','role':'admin'}, headers=H).status_code==201, 'create admin')
chk(su.post('/api/admins', json={'username':'x','password':'short','role':'cleric'}, headers=H).status_code==400, 'reject short password')
chk(su.post('/api/admins', json={'username':'cleo','password':'clericpass1','role':'cleric'}, headers=H).status_code==400, 'reject duplicate username')
chk(su.post('/api/admins', json={'username':'cleo2','password':'clericpass1','role':'wizard'}, headers=H).status_code==400, 'reject invalid role')
chk(su.post('/api/admins', json={'username':'nocsrf','password':'clericpass1','role':'cleric'}).status_code==403, 'create without csrf 403')

# ── cleric gating ──
cl, rc = login('cleo', 'clericpass1', ip='2.2.2.2')
chk(rc.get_json()['role']=='cleric', 'cleric logs in')
clc = rc.get_json()['csrf']
chk(cl.get('/api/ui-text').status_code==200, 'cleric: ui-text read 200')
rid = cl.post('/api/ui-text', json={'category':'welcome_banner','body':'hi'}, headers={'X-CSRF-Token':clc})
chk(rid.status_code==201, 'cleric: ui-text create 201')
chk(cl.get('/api/admins').status_code==403, 'cleric: admins 403 (no account mgmt)')
chk(cl.post('/api/admins', json={'username':'z','password':'clericpass1','role':'cleric'}, headers={'X-CSRF-Token':clc}).status_code==403, 'cleric: create admin 403')

# ── admin gating ──
ad, ra = login('amy', 'adminpass12', ip='3.3.3.3')
chk(ra.get_json()['role']=='admin', 'admin logs in')
chk(ad.get('/api/ui-text').status_code==200, 'admin: ui-text 200 (inherits cleric)')
chk(ad.get('/api/admins').status_code==403, 'admin: admins 403 (not superadmin)')

# ── last-superadmin guard ──
root_id = next(u['id'] for u in al.get_json()['rows'] if u['username']=='root')
amy_id  = next(u['id'] for u in su.get('/api/admins').get_json()['rows'] if u['username']=='amy')
chk(su.delete(f'/api/admins/{root_id}', headers=H).status_code==409, 'cannot delete last superadmin')
chk(su.patch(f'/api/admins/{root_id}', json={'role':'cleric'}, headers=H).status_code==409, 'cannot demote last superadmin')
chk(su.patch(f'/api/admins/{root_id}', json={'active':False}, headers=H).status_code==409, 'cannot deactivate last superadmin')
# promote amy → 2 superadmins → now demoting root is allowed
chk(su.patch(f'/api/admins/{amy_id}', json={'role':'superadmin'}, headers=H).status_code==200, 'promote amy to superadmin')
chk(su.patch(f'/api/admins/{root_id}', json={'role':'cleric'}, headers=H).status_code==200, 'demote root allowed once a 2nd superadmin exists')
su.patch(f'/api/admins/{root_id}', json={'role':'superadmin'}, headers=H)  # restore

# ── self password change ──
chk(cl.post('/api/me/password', json={'current':'wrong','new':'newclericpw1'}, headers={'X-CSRF-Token':clc}).status_code==403, 'self pw: wrong current 403')
chk(cl.post('/api/me/password', json={'current':'clericpass1','new':'short'}, headers={'X-CSRF-Token':clc}).status_code==400, 'self pw: short new 400')
chk(cl.post('/api/me/password', json={'current':'clericpass1','new':'newclericpw1'}, headers={'X-CSRF-Token':clc}).status_code==200, 'self pw: change 200')
chk(login('cleo','newclericpw1', ip='2.2.2.2')[1].status_code==200, 'self pw: new password works')
chk(login('cleo','clericpass1', ip='2.2.2.2')[1].status_code==401, 'self pw: old password rejected')

# ── superadmin resets another account's password ──
cleo_id = next(u['id'] for u in su.get('/api/admins').get_json()['rows'] if u['username']=='cleo')
chk(su.post(f'/api/admins/{cleo_id}/password', json={'password':'resetbysu123'}, headers=H).status_code==200, 'superadmin resets cleric pw')
chk(login('cleo','resetbysu123', ip='2.2.2.2')[1].status_code==200, 'reset password works')

# ── logout + rate limit ──
su.post('/api/logout')
chk(su.get('/api/admins').status_code==401, 'after logout 401')
rl = APP.test_client(); last=None
for _ in range(9):
    last = rl.post('/api/login', json={'username':'root','password':'x'}, environ_overrides={'REMOTE_ADDR':'9.9.9.9'})
chk(last.status_code==429, f'rate limit kicks in ({last.status_code})')

print(f"\n{ok}/{n} multi-admin checks passed")
