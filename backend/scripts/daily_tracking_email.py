import os
import sys
from datetime import datetime
from sqlalchemy import select

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db import SessionLocal
from app.models import Project
from app.services.emailer import send_email

BASE_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

def main():
    db = SessionLocal()
    try:
        # Get all projects that are not cancelled or closed out
        projects = db.query(Project).filter(
            Project.stage != "CLOSEOUT",
            Project.disposition.is_(None)
        ).all()

        print(f"[{datetime.now().isoformat()}] Found {len(projects)} active projects to check.")
        
        sent_count = 0
        for p in projects:
            if not p.pi_email:
                continue
                
            tracking_url = f"{BASE_URL}/track/{p.tracking_token}"
            subject = f"Daily Update: {p.title} (PR/EAR: {p.pr_number})"
            body = f"""Hello {p.pi_name or 'PI'},

Here is your daily update on the project: {p.title}.
Current Stage: {p.stage}

You can track the progress of your project live at any time without logging in by visiting your unique tracking link:
{tracking_url}

Best regards,
IHP Design and Construction Team
"""
            success = send_email(to=p.pi_email, subject=subject, body=body)
            if success:
                sent_count += 1
                
        print(f"[{datetime.now().isoformat()}] Successfully sent {sent_count} tracking emails.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
