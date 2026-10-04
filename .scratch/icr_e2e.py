import json
import urllib.error
import urllib.parse
import urllib.request

from app.core.security import hash_password
from app.db import SessionLocal
from app.models import AuditLog, User

db = SessionLocal()
u = db.query(User).filter(User.username == "deploycheck").one_or_none()
if u is None:
    u = User(
        username="deploycheck",
        full_name="Deploy Check",
        email="",
        hashed_password=hash_password("DeployCheck2026!"),
        role="admin",
        is_active=True,
    )
    db.add(u)
else:
    u.hashed_password = hash_password("DeployCheck2026!")
    u.role = "admin"
    u.is_active = True
db.commit()
uid = u.id
print("temp admin id", uid)
db.close()


def call(method, path, token=None, form=None):
    data = None
    headers = {}
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        "http://127.0.0.1:8000" + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw[:1] in ("{", "[") else raw)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]


st, body = call("POST", "/api/auth/login", form={"username": "deploycheck", "password": "DeployCheck2026!"})
print("LOGIN:", st)
token = body["access_token"]

st, om = call("GET", "/api/projects/om-active", token=token)
print("OM-ACTIVE:", st, "items", len(om["items"]))
icr = [i for i in om["items"] if i.get("app_disposition") == "ICR"]
print("   in-app ICR rows:", len(icr))
for i in icr:
    print("   ", i["pr_key"], "in_app=", i["in_app"], "tag=", i["tag"])

st, pull = call("POST", "/api/projects/om-active/pull-icr", token=token)
print("PULL-ICR (re-run):", st, {k: v for k, v in pull.items() if k != "items"})

st, stats = call("GET", "/api/projects/stats", token=token)
print("STATS:", st, json.dumps(stats.get("by_disposition") if isinstance(stats, dict) else stats))

db = SessionLocal()
deleted_audit = db.query(AuditLog).filter(AuditLog.user_id == uid).delete(synchronize_session=False)
db.query(User).filter(User.id == uid).delete(synchronize_session=False)
db.commit()
print("cleanup: audit rows", deleted_audit)
print("users left:", sorted(x.username for x in db.query(User).all()))
print("audit rows with user", uid, ":", db.query(AuditLog).filter(AuditLog.user_id == uid).count())
db.close()
