from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime
import os

from database import get_db, init_db
from models import User, Goal, Checkin, UserRole, GoalStatus, UoMType, CheckinStatus, EscalationRule
from schemas import Token, UserOut, LoginRequest
from auth import verify_password, create_access_token, get_current_user, hash_password
from routers import router
from services import create_notification

app = FastAPI()
origins = [
    "https://atomberg-hackathon-6b4o.onrender.com",
    "http://localhost:3000", # keeping local dev working
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

_INDEX_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")


@app.get("/", include_in_schema=False)
def serve_frontend():
    try:
        with open(_INDEX_HTML, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content=content)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"index.html not found at: {_INDEX_HTML}")


@app.post("/api/auth/token", response_model=Token)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer", "user": user}


@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


def seed_data(db: Session):
    if db.query(User).first():
        return  # already seeded

    admin = User(name="HR Admin", email="admin@atomquest.com",
                 hashed_password=hash_password("admin123"),
                 role=UserRole.admin, department="HR")
    db.add(admin)
    db.flush()

    mgr1 = User(name="Priya Sharma", email="manager@atomquest.com",
                hashed_password=hash_password("manager123"),
                role=UserRole.manager, department="Engineering", manager_id=admin.id)
    db.add(mgr1)
    db.flush()

    emp1 = User(name="Arjun Reddy", email="employee@atomquest.com",
                hashed_password=hash_password("employee123"),
                role=UserRole.employee, department="Engineering", manager_id=mgr1.id)
    emp2 = User(name="Sneha Patel", email="sneha@atomquest.com",
                hashed_password=hash_password("employee123"),
                role=UserRole.employee, department="Engineering", manager_id=mgr1.id)
    emp3 = User(name="Ravi Kumar", email="ravi@atomquest.com",
                hashed_password=hash_password("employee123"),
                role=UserRole.employee, department="Sales", manager_id=mgr1.id)
    db.add_all([emp1, emp2, emp3])
    db.flush()

    # Arjun's goals — already approved
    g1 = Goal(owner_id=emp1.id, thrust_area="Revenue Growth", title="Increase Q1 Sales Revenue",
              description="Grow sales revenue by 25% over Q1 baseline",
              uom_type=UoMType.min, target=1250000.0, weightage=40.0,
              status=GoalStatus.approved, is_locked=True)
    g2 = Goal(owner_id=emp1.id, thrust_area="Customer Success", title="Reduce Support TAT",
              description="Reduce average ticket resolution time",
              uom_type=UoMType.max, target=24.0, weightage=30.0,
              status=GoalStatus.approved, is_locked=True)
    g3 = Goal(owner_id=emp1.id, thrust_area="Safety", title="Zero Safety Incidents",
              description="Maintain zero workplace incidents",
              uom_type=UoMType.zero, target=0.0, weightage=15.0,
              status=GoalStatus.approved, is_locked=True)
    g4 = Goal(owner_id=emp1.id, thrust_area="Learning", title="Complete AWS Certification",
              description="Obtain AWS Solutions Architect certification",
              uom_type=UoMType.timeline, target=1.0,
              deadline=datetime(2025, 12, 31), weightage=15.0,
              status=GoalStatus.approved, is_locked=True)
    db.add_all([g1, g2, g3, g4])
    db.flush()

    c1 = Checkin(goal_id=g1.id, quarter="Q1", actual_achievement=1100000.0,
                 status=CheckinStatus.on_track, progress_score=88.0)
    c2 = Checkin(goal_id=g1.id, quarter="Q2", actual_achievement=1300000.0,
                 status=CheckinStatus.completed, progress_score=104.0)
    c3 = Checkin(goal_id=g2.id, quarter="Q1", actual_achievement=20.0,
                 status=CheckinStatus.on_track, progress_score=83.3,
                 manager_comment="Good improvement! Keep it up.")
    c4 = Checkin(goal_id=g3.id, quarter="Q1", actual_achievement=0.0,
                 status=CheckinStatus.on_track, progress_score=100.0)
    db.add_all([c1, c2, c3, c4])

    # Sneha's goals — pending approval
    g5 = Goal(owner_id=emp2.id, thrust_area="Revenue Growth", title="New Client Acquisition",
              uom_type=UoMType.min, target=15.0, weightage=50.0, status=GoalStatus.submitted)
    g6 = Goal(owner_id=emp2.id, thrust_area="Learning", title="Complete React Certification",
              uom_type=UoMType.timeline, target=1.0, deadline=datetime(2025, 9, 30),
              weightage=50.0, status=GoalStatus.submitted)
    db.add_all([g5, g6])

    # Ravi's goals — still in draft
    g7 = Goal(owner_id=emp3.id, thrust_area="Revenue Growth", title="Exceed Sales Target",
              uom_type=UoMType.min, target=500000.0, weightage=60.0, status=GoalStatus.draft)
    g8 = Goal(owner_id=emp3.id, thrust_area="Customer Success", title="Improve NPS Score",
              uom_type=UoMType.min, target=75.0, weightage=40.0, status=GoalStatus.draft)
    db.add_all([g7, g8])

    create_notification(db, emp1.id, "Welcome to AtomQuest! 🎯",
                        "Your goals have been set up. Start your Q3 check-in now.", "success")
    create_notification(db, mgr1.id, "Pending Approvals",
                        "Sneha Patel has submitted goals for your approval.", "action")
    create_notification(db, admin.id, "Portal Initialized",
                        "AtomQuest Goal Portal is ready. 4 employees, 8 goals loaded.", "info")

    r1 = EscalationRule(name="Goal Not Submitted (7 days)", rule_type="goal_not_submitted", trigger_days=7, is_active=True)
    r2 = EscalationRule(name="Goal Not Approved (5 days)", rule_type="goal_not_approved", trigger_days=5, is_active=True)
    r3 = EscalationRule(name="Check-in Overdue (14 days)", rule_type="checkin_not_done", trigger_days=14, is_active=True)
    db.add_all([r1, r2, r3])

    db.commit()
    print("Seed data loaded")


@app.on_event("startup")
def startup():
    init_db()
    db = next(get_db())
    try:
        seed_data(db)
    except Exception as e:
        print(f"Seed error (non-fatal): {e}")
        db.rollback()
    print("AtomQuest Goal Portal running at http://localhost:8000")
    print("  admin@atomquest.com / admin123")
    print("  manager@atomquest.com / manager123")
    print("  employee@atomquest.com / employee123")
