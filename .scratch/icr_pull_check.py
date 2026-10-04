import json
from app.db import SessionLocal
from app.models import Project, User
from app.services.tracker_sources import om_path
from app.services.tracker_import import parse_om_active_prs
from app.api.projects import pull_icr_projects

db = SessionLocal()
before = {p.pr_number: (p.disposition, p.stage) for p in db.query(Project).all()}
print("REGISTER BEFORE:", len(before))

rows = [
    r
    for r in parse_om_active_prs(om_path(), tabs=("Active Equipment PRs",))
    if r.category == "CONSTRUCTION"
]
print("O&M ICR ROWS:", len(rows))
for r in rows:
    print("   ", r.pr_key, "|", r.classification_raw, "|", r.status, "|", (r.title or "")[:46])

res = pull_icr_projects(db=db, user=db.get(User, 1))
print("PULL:", json.dumps({k: v for k, v in res.items() if k != "items"}, default=str))
for it in res["items"]:
    print("   ", it["pr_key"], it["action"], it["changes"], "-> id", it["project_id"])

after = {p.pr_number: (p.disposition, p.stage) for p in db.query(Project).all()}
print("REGISTER AFTER:", len(after))
print("ICR DISPOSITION TOTAL:", sum(1 for v in after.values() if v[0] == "ICR"))
for it in res["items"]:
    print("   ", it["pr_key"], after.get(it["pr_key"]))
db.close()
