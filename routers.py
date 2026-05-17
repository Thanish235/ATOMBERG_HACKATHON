from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timedelta
from typing import List, Optional
import io, csv

from database import get_db
from models import User, Goal, Checkin, AuditLog, Notification, UserRole, GoalStatus, UoMType, EscalationRule, EscalationLog, EmailNotificationLog
from schemas import (
    GoalCreate, GoalUpdate, GoalOut, CheckinCreate, CheckinManagerUpdate,
    CheckinOut, AuditLogOut, NotificationOut, SharedGoalPush,
    UserCreate, UserOut, UserOutWithTeam, DashboardStats,
    EscalationRuleCreate, EscalationRuleOut, EscalationLogOut,
    EmailLogOut, EmailSettingsUpdate
)
from auth import get_current_user, hash_password, require_role
from services import compute_progress_score, create_notification, log_email_notification, send_notification_with_log

router = APIRouter()


# --- Users ---

@router.post("/users", response_model=UserOut)
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, "Email already registered")
    user = User(
        name=data.name, email=data.email,
        hashed_password=hash_password(data.password),
        role=data.role, department=data.department,
        manager_id=data.manager_id
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/users/me", response_model=UserOutWithTeam)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).options(
        joinedload(User.direct_reports),
        joinedload(User.manager)
    ).filter(User.id == current_user.id).first()
    return user


@router.get("/users", response_model=List[UserOut])
def list_users(
    role: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin))
):
    q = db.query(User)
    if role:
        q = q.filter(User.role == role)
    return q.all()


@router.get("/users/{user_id}", response_model=UserOutWithTeam)
def get_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user = db.query(User).options(
        joinedload(User.direct_reports),
        joinedload(User.manager)
    ).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    return user


# --- Goals ---

def _validate_goal_weightage(db: Session, owner_id: int, new_weightage: float, exclude_id: int = None):
    if new_weightage < 10:
        raise HTTPException(400, f"Minimum weightage per goal is 10% (provided: {new_weightage}%)")
    q = db.query(Goal).filter(Goal.owner_id == owner_id, Goal.status != GoalStatus.returned)
    if exclude_id:
        q = q.filter(Goal.id != exclude_id)
    existing = q.all()
    total = sum(g.weightage for g in existing) + new_weightage
    if total > 100:
        raise HTTPException(400, f"Total weightage would exceed 100% (current: {total - new_weightage}%, adding: {new_weightage}%)")
    if len(existing) >= 8:
        raise HTTPException(400, "Maximum 8 goals per employee reached")


@router.post("/goals", response_model=GoalOut)
def create_goal(data: GoalCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _validate_goal_weightage(db, current_user.id, data.weightage)
    goal = Goal(owner_id=current_user.id, **data.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


@router.get("/goals", response_model=List[GoalOut])
def list_goals(
    owner_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Goal).options(joinedload(Goal.owner), joinedload(Goal.checkins))
    if current_user.role == UserRole.employee:
        q = q.filter(Goal.owner_id == current_user.id)
    elif current_user.role == UserRole.manager:
        team_ids = [u.id for u in current_user.direct_reports] + [current_user.id]
        if owner_id and owner_id in team_ids:
            q = q.filter(Goal.owner_id == owner_id)
        else:
            q = q.filter(Goal.owner_id.in_(team_ids))
    else:
        if owner_id:
            q = q.filter(Goal.owner_id == owner_id)
    if status:
        q = q.filter(Goal.status == status)
    return q.all()


@router.get("/goals/{goal_id}", response_model=GoalOut)
def get_goal(goal_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    goal = db.query(Goal).options(joinedload(Goal.owner), joinedload(Goal.checkins)).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(404, "Goal not found")
    return goal


@router.put("/goals/{goal_id}", response_model=GoalOut)
def update_goal(
    goal_id: int, data: GoalUpdate, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(404, "Goal not found")

    is_owner = goal.owner_id == current_user.id
    is_manager = current_user.role in [UserRole.manager, UserRole.admin]

    if goal.is_locked and not is_manager:
        raise HTTPException(403, "Goal is locked. Contact admin to unlock.")
    if not is_owner and not is_manager:
        raise HTTPException(403, "Cannot edit this goal")

    update_data = data.model_dump(exclude_none=True)
    if "weightage" in update_data and update_data["weightage"] != goal.weightage:
        _validate_goal_weightage(db, goal.owner_id, update_data["weightage"], exclude_id=goal_id)

    for field, new_val in update_data.items():
        old_val = getattr(goal, field, None)
        if old_val != new_val:
            db.add(AuditLog(
                goal_id=goal.id,
                changed_by_id=current_user.id,
                field_changed=field,
                old_value=str(old_val),
                new_value=str(new_val),
                note="Post-lock edit" if goal.is_locked else None
            ))
        setattr(goal, field, new_val)

    goal.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(goal)
    return goal


@router.post("/goals/{goal_id}/submit", response_model=GoalOut)
def submit_goal(goal_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    goal = db.query(Goal).filter(Goal.id == goal_id, Goal.owner_id == current_user.id).first()
    if not goal:
        raise HTTPException(404, "Goal not found")
    if goal.status not in [GoalStatus.draft, GoalStatus.returned]:
        raise HTTPException(400, f"Cannot submit goal in '{goal.status}' status")

    all_goals = db.query(Goal).filter(
        Goal.owner_id == current_user.id,
        ~Goal.status.in_([GoalStatus.returned])
    ).all()
    total = sum(g.weightage for g in all_goals)
    if abs(total - 100.0) > 0.01:
        raise HTTPException(400, f"Total weightage must equal 100% before submitting. Current: {total}%")

    goal.status = GoalStatus.submitted
    goal.updated_at = datetime.utcnow()

    if current_user.manager_id:
        create_notification(
            db, current_user.manager_id,
            "Goal Submitted for Approval",
            f"{current_user.name} submitted '{goal.title}' for your approval.",
            notif_type="action",
            link=f"/goals/{goal.id}"
        )

    db.commit()
    db.refresh(goal)
    return goal


@router.post("/goals/{goal_id}/approve", response_model=GoalOut)
def approve_goal(
    goal_id: int, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin))
):
    goal = db.query(Goal).options(joinedload(Goal.owner)).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(404, "Goal not found")
    if goal.status != GoalStatus.submitted:
        raise HTTPException(400, "Goal must be submitted before it can be approved")

    goal.status = GoalStatus.approved
    goal.is_locked = True
    goal.updated_at = datetime.utcnow()

    create_notification(
        db, goal.owner_id,
        "Goal Approved ✓",
        f"Your goal '{goal.title}' has been approved and locked.",
        notif_type="success",
        link=f"/goals/{goal.id}"
    )

    db.commit()
    db.refresh(goal)
    return goal


@router.post("/goals/{goal_id}/return", response_model=GoalOut)
def return_goal(
    goal_id: int, comment: str, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin))
):
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(404, "Goal not found")
    if goal.status != GoalStatus.submitted:
        raise HTTPException(400, "Goal must be submitted to return it")

    goal.status = GoalStatus.returned
    goal.manager_comment = comment
    goal.updated_at = datetime.utcnow()

    create_notification(
        db, goal.owner_id,
        "Goal Returned for Revision",
        f"Your goal '{goal.title}' was returned. Feedback: {comment}",
        notif_type="warning",
        link=f"/goals/{goal.id}"
    )

    db.commit()
    db.refresh(goal)
    return goal


@router.post("/goals/{goal_id}/unlock")
def unlock_goal(
    goal_id: int, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin))
):
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(404, "Goal not found")
    goal.is_locked = False
    db.add(AuditLog(
        goal_id=goal.id,
        changed_by_id=current_user.id,
        field_changed="is_locked",
        old_value="True",
        new_value="False",
        note=f"Admin unlock by {current_user.name}"
    ))
    db.commit()
    return {"message": "Goal unlocked"}


@router.post("/shared-goals/push", response_model=List[GoalOut])
def push_shared_goal(
    data: SharedGoalPush, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin))
):
    parent = db.query(Goal).filter(Goal.id == data.goal_id).first()
    if not parent:
        raise HTTPException(404, "Parent goal not found")

    created = []
    for emp_id in data.employee_ids:
        emp = db.query(User).filter(User.id == emp_id).first()
        if not emp:
            continue
        already_has = db.query(Goal).filter(Goal.parent_goal_id == parent.id, Goal.owner_id == emp_id).first()
        if already_has:
            continue
        shared = Goal(
            owner_id=emp_id,
            parent_goal_id=parent.id,
            thrust_area=parent.thrust_area,
            title=parent.title,
            description=parent.description,
            uom_type=parent.uom_type,
            target=parent.target,
            deadline=parent.deadline,
            weightage=10.0,  # employee adjusts this
            is_shared=True,
            status=GoalStatus.draft
        )
        db.add(shared)
        create_notification(
            db, emp_id,
            "Shared Goal Assigned",
            f"A departmental goal '{parent.title}' was assigned to you. Set your weightage before submitting.",
            notif_type="action",
            link="/goals"
        )
        created.append(shared)

    db.commit()
    for g in created:
        db.refresh(g)
    return created


# --- Checkins ---

@router.post("/goals/{goal_id}/checkins", response_model=CheckinOut)
def create_checkin(
    goal_id: int, data: CheckinCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(404, "Goal not found")
    if goal.owner_id != current_user.id:
        raise HTTPException(403, "Not your goal")
    if goal.status != GoalStatus.approved:
        raise HTTPException(400, "Goal must be approved before check-ins can be added")

    existing = db.query(Checkin).filter(Checkin.goal_id == goal_id, Checkin.quarter == data.quarter).first()
    if existing:
        raise HTTPException(400, f"Check-in for {data.quarter} already exists. Use PUT to update.")

    score = compute_progress_score(
        goal.uom_type, goal.target, data.actual_achievement,
        goal.deadline, data.actual_date
    )
    checkin = Checkin(
        goal_id=goal_id,
        quarter=data.quarter,
        actual_achievement=data.actual_achievement,
        actual_date=data.actual_date,
        status=data.status,
        progress_score=score
    )
    db.add(checkin)

    if current_user.manager_id:
        create_notification(
            db, current_user.manager_id,
            f"Check-in Update — {data.quarter}",
            f"{current_user.name} updated achievement for '{goal.title}'",
            notif_type="info",
            link=f"/goals/{goal_id}"
        )

    db.commit()
    db.refresh(checkin)
    return checkin


@router.put("/goals/{goal_id}/checkins/{quarter}", response_model=CheckinOut)
def update_checkin(
    goal_id: int, quarter: str, data: CheckinCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(404, "Goal not found")
    if goal.owner_id != current_user.id:
        raise HTTPException(403, "Not your goal")

    checkin = db.query(Checkin).filter(Checkin.goal_id == goal_id, Checkin.quarter == quarter).first()
    if not checkin:
        raise HTTPException(404, "Check-in not found")

    checkin.actual_achievement = data.actual_achievement
    checkin.actual_date = data.actual_date
    checkin.status = data.status
    checkin.progress_score = compute_progress_score(
        goal.uom_type, goal.target, data.actual_achievement,
        goal.deadline, data.actual_date
    )
    checkin.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(checkin)
    return checkin


@router.post("/goals/{goal_id}/checkins/{quarter}/comment", response_model=CheckinOut)
def manager_comment(
    goal_id: int, quarter: str, data: CheckinManagerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin))
):
    checkin = db.query(Checkin).filter(Checkin.goal_id == goal_id, Checkin.quarter == quarter).first()
    if not checkin:
        raise HTTPException(404, "Check-in not found")
    checkin.manager_comment = data.manager_comment
    checkin.updated_at = datetime.utcnow()
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if goal:
        create_notification(
            db, goal.owner_id,
            "Manager Feedback on Check-in",
            f"Your manager left feedback on your {quarter} check-in for '{goal.title}'",
            notif_type="info",
            link=f"/goals/{goal_id}"
        )
    db.commit()
    db.refresh(checkin)
    return checkin


# --- Audit Logs ---

@router.get("/goals/{goal_id}/audit", response_model=List[AuditLogOut])
def get_audit_log(
    goal_id: int, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin))
):
    logs = db.query(AuditLog).options(joinedload(AuditLog.changed_by)).filter(
        AuditLog.goal_id == goal_id
    ).order_by(AuditLog.changed_at.desc()).all()
    return logs


# --- Notifications ---

@router.get("/notifications", response_model=List[NotificationOut])
def get_notifications(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Notification).filter(Notification.user_id == current_user.id)
    if unread_only:
        q = q.filter(Notification.is_read == False)
    return q.order_by(Notification.created_at.desc()).limit(50).all()


@router.post("/notifications/{notif_id}/read")
def mark_read(notif_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    n = db.query(Notification).filter(Notification.id == notif_id, Notification.user_id == current_user.id).first()
    if n:
        n.is_read = True
        db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_read(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db.query(Notification).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return {"ok": True}


# --- Reports & Dashboard ---

@router.get("/reports/achievement")
def achievement_report(
    format: str = "json",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin))
):
    goals = db.query(Goal).options(
        joinedload(Goal.owner), joinedload(Goal.checkins)
    ).filter(Goal.status == GoalStatus.approved).all()

    rows = []
    for g in goals:
        base = {
            "employee_name": g.owner.name,
            "employee_email": g.owner.email,
            "department": g.owner.department or "-",
            "goal_title": g.title,
            "thrust_area": g.thrust_area,
            "uom_type": g.uom_type,
            "target": g.target,
        }
        if g.checkins:
            for c in g.checkins:
                rows.append({**base, "quarter": c.quarter, "actual": c.actual_achievement,
                              "progress_score": c.progress_score, "status": c.status})
        else:
            rows.append({**base, "quarter": "-", "actual": None, "progress_score": None, "status": "no_checkin"})

    if format == "csv":
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=achievement_report.csv"}
        )

    return rows


@router.get("/reports/dashboard")
def dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == UserRole.employee:
        my_goals = db.query(Goal).filter(Goal.owner_id == current_user.id).all()
        checkins = db.query(Checkin).join(Goal).filter(Goal.owner_id == current_user.id).all()
        return {
            "total_goals": len(my_goals),
            "approved_goals": len([g for g in my_goals if g.status == GoalStatus.approved]),
            "total_checkins": len(checkins),
            "avg_progress": round(sum(c.progress_score or 0 for c in checkins) / len(checkins), 1) if checkins else 0,
            "goals_by_status": _count_by_status(my_goals),
            "checkins_by_quarter": _count_checkins_by_quarter(checkins),
        }
    elif current_user.role == UserRole.manager:
        team_ids = [u.id for u in current_user.direct_reports]
        goals = db.query(Goal).filter(Goal.owner_id.in_(team_ids)).all() if team_ids else []
        checkins = db.query(Checkin).join(Goal).filter(Goal.owner_id.in_(team_ids)).all() if team_ids else []
        return {
            "team_size": len(team_ids),
            "total_goals": len(goals),
            "pending_approvals": len([g for g in goals if g.status == GoalStatus.submitted]),
            "approved_goals": len([g for g in goals if g.status == GoalStatus.approved]),
            "total_checkins": len(checkins),
            "goals_by_status": _count_by_status(goals),
            "team_progress": _team_progress(db, team_ids),
        }
    else:  # admin
        total_users = db.query(User).filter(User.role == UserRole.employee).count()
        total_goals = db.query(Goal).count()
        approved_goals = db.query(Goal).filter(Goal.status == GoalStatus.approved).count()
        submitted_goals = db.query(Goal).filter(Goal.status == GoalStatus.submitted).count()
        total_checkins = db.query(Checkin).count()
        all_goals = db.query(Goal).all()
        return {
            "total_employees": total_users,
            "total_goals": total_goals,
            "approved_goals": approved_goals,
            "submitted_goals": submitted_goals,
            "total_checkins": total_checkins,
            "goals_by_status": _count_by_status(all_goals),
            "completion_rate": round((approved_goals / total_goals * 100) if total_goals else 0, 1),
            "dept_breakdown": _dept_breakdown(db),
        }


def _count_by_status(goals):
    result = {}
    for g in goals:
        result[g.status] = result.get(g.status, 0) + 1
    return result


def _count_checkins_by_quarter(checkins):
    result = {}
    for c in checkins:
        result[c.quarter] = result.get(c.quarter, 0) + 1
    return result


def _team_progress(db, team_ids):
    if not team_ids:
        return []
    result = []
    for uid in team_ids:
        user = db.query(User).filter(User.id == uid).first()
        goals = db.query(Goal).filter(Goal.owner_id == uid, Goal.status == GoalStatus.approved).all()
        checkins = db.query(Checkin).join(Goal).filter(Goal.owner_id == uid).all()
        avg = round(sum(c.progress_score or 0 for c in checkins) / len(checkins), 1) if checkins else 0
        result.append({"name": user.name, "approved_goals": len(goals), "avg_progress": avg})
    return result


def _dept_breakdown(db):
    users = db.query(User).filter(User.role == UserRole.employee).all()
    depts = {}
    for u in users:
        d = u.department or "Unassigned"
        if d not in depts:
            depts[d] = {"department": d, "employees": 0, "goals": 0}
        depts[d]["employees"] += 1
        depts[d]["goals"] += db.query(Goal).filter(Goal.owner_id == u.id).count()
    return list(depts.values())


# --- Analytics ---

@router.get("/analytics/qoq")
def qoq_trends(
    employee_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin))
):
    q = db.query(Checkin).join(Goal)
    if employee_id:
        q = q.filter(Goal.owner_id == employee_id)
    elif current_user.role == UserRole.manager:
        team_ids = [u.id for u in current_user.direct_reports]
        q = q.filter(Goal.owner_id.in_(team_ids))

    checkins = q.all()
    by_quarter = {}
    for c in checkins:
        qtr = c.quarter
        if qtr not in by_quarter:
            by_quarter[qtr] = {"quarter": qtr, "count": 0, "total_score": 0, "avg_score": 0}
        by_quarter[qtr]["count"] += 1
        by_quarter[qtr]["total_score"] += c.progress_score or 0

    for qtr in by_quarter:
        cnt = by_quarter[qtr]["count"]
        by_quarter[qtr]["avg_score"] = round(by_quarter[qtr]["total_score"] / cnt, 1) if cnt else 0

    order = ["Q1", "Q2", "Q3", "Q4"]
    return sorted(by_quarter.values(), key=lambda x: order.index(x["quarter"]) if x["quarter"] in order else 99)


@router.get("/analytics/thrust-areas")
def thrust_area_analysis(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin))
):
    q = db.query(Goal)
    if current_user.role == UserRole.manager:
        team_ids = [u.id for u in current_user.direct_reports]
        q = q.filter(Goal.owner_id.in_(team_ids))

    goals = q.all()
    by_thrust = {}
    for g in goals:
        ta = g.thrust_area
        if ta not in by_thrust:
            by_thrust[ta] = {"thrust_area": ta, "total": 0, "approved": 0, "avg_weightage": 0, "weightages": []}
        by_thrust[ta]["total"] += 1
        if g.status == GoalStatus.approved:
            by_thrust[ta]["approved"] += 1
        by_thrust[ta]["weightages"].append(g.weightage)

    for ta in by_thrust:
        ws = by_thrust[ta].pop("weightages")
        by_thrust[ta]["avg_weightage"] = round(sum(ws) / len(ws), 1) if ws else 0

    return list(by_thrust.values())


@router.get("/analytics/manager-effectiveness")
def manager_effectiveness(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin))
):
    managers = db.query(User).filter(User.role == UserRole.manager).all()
    result = []
    for mgr in managers:
        team_ids = [u.id for u in mgr.direct_reports]
        if not team_ids:
            continue
        approved = db.query(Goal).filter(Goal.owner_id.in_(team_ids), Goal.status == GoalStatus.approved).count()
        submitted = db.query(Goal).filter(Goal.owner_id.in_(team_ids), Goal.status == GoalStatus.submitted).count()
        commented = db.query(Checkin).join(Goal).filter(
            Goal.owner_id.in_(team_ids),
            Checkin.manager_comment.isnot(None)
        ).count()
        result.append({
            "manager": mgr.name,
            "team_size": len(team_ids),
            "approved_goals": approved,
            "pending_approvals": submitted,
            "checkins_commented": commented,
        })
    return result


# --- Email / Teams Integration ---

_email_settings = {
    "smtp_host": "smtp.atomquest.com",
    "smtp_port": 587,
    "teams_webhook_url": "",
    "notify_on_submission": True,
    "notify_on_approval": True,
    "notify_on_rejection": True,
    "notify_on_checkin": True,
}


@router.get("/integrations/email-settings")
def get_email_settings(current_user: User = Depends(require_role(UserRole.admin))):
    return _email_settings


@router.put("/integrations/email-settings")
def update_email_settings(
    data: EmailSettingsUpdate,
    current_user: User = Depends(require_role(UserRole.admin))
):
    _email_settings.update(data.model_dump(exclude_none=True))
    return {"ok": True, "settings": _email_settings}


@router.get("/integrations/email-logs", response_model=List[EmailLogOut])
def get_email_logs(
    channel: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin))
):
    q = db.query(EmailNotificationLog)
    if channel:
        q = q.filter(EmailNotificationLog.channel == channel)
    return q.order_by(EmailNotificationLog.sent_at.desc()).limit(limit).all()


@router.post("/integrations/test-email")
def test_email_notification(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin))
):
    send_notification_with_log(
        db, current_user.id,
        "Test Notification — AtomQuest",
        "This is a test notification from the AtomQuest portal. Email & Teams integration is working.",
        notif_type="info",
        event_type="test",
        channels=["email", "teams"]
    )
    db.commit()
    return {"ok": True, "message": "Test notification logged and sent"}


@router.post("/integrations/test-teams")
def test_teams_notification(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin))
):
    send_notification_with_log(
        db, current_user.id,
        "Teams Bot — Goal Update",
        "AtomQuest Teams Bot: Your portal is connected. Adaptive cards will appear here on key events.",
        notif_type="info",
        event_type="teams_test",
        channels=["teams"]
    )
    db.commit()
    return {"ok": True, "message": "Teams test notification queued"}


@router.get("/integrations/stats")
def integration_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin))
):
    total = db.query(EmailNotificationLog).count()
    by_channel = {ch: db.query(EmailNotificationLog).filter(EmailNotificationLog.channel == ch).count()
                  for ch in ["email", "teams"]}
    by_event = {}
    for log in db.query(EmailNotificationLog).all():
        et = log.event_type or "other"
        by_event[et] = by_event.get(et, 0) + 1
    return {"total_notifications": total, "by_channel": by_channel, "by_event_type": by_event, "settings": _email_settings}


# --- Escalation Engine ---

@router.get("/escalation/rules", response_model=List[EscalationRuleOut])
def list_escalation_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin))
):
    return db.query(EscalationRule).all()


@router.post("/escalation/rules", response_model=EscalationRuleOut)
def create_escalation_rule(
    data: EscalationRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin))
):
    rule = EscalationRule(**data.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/escalation/rules/{rule_id}", response_model=EscalationRuleOut)
def update_escalation_rule(
    rule_id: int, data: EscalationRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin))
):
    rule = db.query(EscalationRule).filter(EscalationRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule not found")
    for k, v in data.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/escalation/rules/{rule_id}")
def delete_escalation_rule(
    rule_id: int, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin))
):
    rule = db.query(EscalationRule).filter(EscalationRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule not found")
    db.delete(rule)
    db.commit()
    return {"ok": True}


@router.post("/escalation/run")
def run_escalation_engine(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin))
):
    rules = db.query(EscalationRule).filter(EscalationRule.is_active == True).all()
    now = datetime.utcnow()
    triggered = []

    for rule in rules:
        threshold = timedelta(days=rule.trigger_days)

        if rule.rule_type == "goal_not_submitted":
            for emp in db.query(User).filter(User.role == UserRole.employee).all():
                old_drafts = db.query(Goal).filter(
                    Goal.owner_id == emp.id,
                    Goal.status == GoalStatus.draft,
                    Goal.created_at <= now - threshold
                ).all()
                if not old_drafts:
                    continue
                already_open = db.query(EscalationLog).filter(
                    EscalationLog.rule_id == rule.id,
                    EscalationLog.user_id == emp.id,
                    EscalationLog.status == "open"
                ).first()
                if not already_open:
                    msg = f"{emp.name} has {len(old_drafts)} draft goal(s) not submitted for over {rule.trigger_days} days."
                    db.add(EscalationLog(rule_id=rule.id, user_id=emp.id, level=1, message=msg))
                    create_notification(db, emp.id, "⚠️ Submit Your Goals",
                        f"You have {len(old_drafts)} draft goal(s) pending submission.", "warning")
                    if emp.manager_id:
                        create_notification(db, emp.manager_id, f"Escalation: {emp.name} hasn't submitted goals", msg, "warning")
                    triggered.append({"rule": rule.name, "user": emp.name, "type": rule.rule_type})

        elif rule.rule_type == "goal_not_approved":
            for g in db.query(Goal).filter(Goal.status == GoalStatus.submitted, Goal.updated_at <= now - threshold).all():
                owner = db.query(User).filter(User.id == g.owner_id).first()
                if not owner:
                    continue
                already_open = db.query(EscalationLog).filter(
                    EscalationLog.rule_id == rule.id,
                    EscalationLog.user_id == owner.id,
                    EscalationLog.status == "open"
                ).first()
                if not already_open:
                    msg = f"'{g.title}' by {owner.name} has been pending approval for over {rule.trigger_days} days."
                    db.add(EscalationLog(rule_id=rule.id, user_id=owner.id, level=2, message=msg))
                    if owner.manager_id:
                        create_notification(db, owner.manager_id, "⚠️ Pending Approval Overdue", msg, "warning")
                    triggered.append({"rule": rule.name, "user": owner.name, "type": rule.rule_type})

        elif rule.rule_type == "checkin_not_done":
            month = now.month
            if month in [7, 8, 9]:
                expected_q = "Q1"
            elif month in [10, 11, 12]:
                expected_q = "Q2"
            elif month in [1, 2, 3]:
                expected_q = "Q3"
            else:
                expected_q = None  # goal-setting phase, nothing to check

            if expected_q:
                for emp in db.query(User).filter(User.role == UserRole.employee).all():
                    approved_goals = db.query(Goal).filter(
                        Goal.owner_id == emp.id, Goal.status == GoalStatus.approved
                    ).all()
                    for g in approved_goals:
                        has_checkin = db.query(Checkin).filter(
                            Checkin.goal_id == g.id, Checkin.quarter == expected_q
                        ).first()
                        if not has_checkin:
                            already_open = db.query(EscalationLog).filter(
                                EscalationLog.rule_id == rule.id,
                                EscalationLog.user_id == emp.id,
                                EscalationLog.status == "open"
                            ).first()
                            if not already_open:
                                msg = f"{emp.name} hasn't completed {expected_q} check-in for '{g.title}'."
                                db.add(EscalationLog(rule_id=rule.id, user_id=emp.id, level=1, message=msg))
                                create_notification(db, emp.id, f"⚠️ {expected_q} Check-in Overdue",
                                    f"Please complete your {expected_q} check-in for '{g.title}'.", "warning")
                                triggered.append({"rule": rule.name, "user": emp.name, "type": rule.rule_type})
                            break  # one escalation per employee per rule

    db.commit()
    return {"triggered": len(triggered), "details": triggered}


@router.get("/escalation/logs", response_model=List[EscalationLogOut])
def list_escalation_logs(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin))
):
    q = db.query(EscalationLog)
    if status:
        q = q.filter(EscalationLog.status == status)
    return q.order_by(EscalationLog.created_at.desc()).limit(100).all()


@router.post("/escalation/logs/{log_id}/resolve")
def resolve_escalation(
    log_id: int, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin))
):
    log = db.query(EscalationLog).filter(EscalationLog.id == log_id).first()
    if not log:
        raise HTTPException(404, "Log not found")
    log.status = "resolved"
    log.resolved_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.get("/escalation/stats")
def escalation_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin))
):
    total = db.query(EscalationLog).count()
    open_count = db.query(EscalationLog).filter(EscalationLog.status == "open").count()
    resolved = db.query(EscalationLog).filter(EscalationLog.status == "resolved").count()
    by_type = {}
    for log in db.query(EscalationLog).join(EscalationRule).all():
        rt = log.rule.rule_type
        by_type[rt] = by_type.get(rt, 0) + 1
    return {"total": total, "open": open_count, "resolved": resolved, "by_rule_type": by_type}


# --- Enhanced Analytics ---

@router.get("/analytics/department-heatmap")
def department_heatmap(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin))
):
    employees = db.query(User).filter(User.role == UserRole.employee).all()
    quarters = ["Q1", "Q2", "Q3", "Q4"]
    depts = {}
    for emp in employees:
        dept = emp.department or "Unassigned"
        if dept not in depts:
            depts[dept] = {q: {"total": 0, "done": 0} for q in quarters}
        for g in db.query(Goal).filter(Goal.owner_id == emp.id, Goal.status == GoalStatus.approved).all():
            for q in quarters:
                checkin = db.query(Checkin).filter(Checkin.goal_id == g.id, Checkin.quarter == q).first()
                depts[dept][q]["total"] += 1
                if checkin and checkin.status.value == "completed":
                    depts[dept][q]["done"] += 1

    result = []
    for dept, qdata in depts.items():
        row = {"department": dept}
        for q in quarters:
            total = qdata[q]["total"]
            done = qdata[q]["done"]
            row[q] = round((done / total * 100) if total else 0, 1)
        result.append(row)
    return result


@router.get("/analytics/individual-trend")
def individual_trend(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == UserRole.employee and current_user.id != employee_id:
        raise HTTPException(403, "Cannot view another employee's data")

    checkins = db.query(Checkin).join(Goal).filter(Goal.owner_id == employee_id).all()
    by_quarter = {}
    for c in checkins:
        q = c.quarter
        if q not in by_quarter:
            by_quarter[q] = {"quarter": q, "scores": [], "avg_score": 0}
        by_quarter[q]["scores"].append(c.progress_score or 0)

    for q in by_quarter:
        sc = by_quarter[q]["scores"]
        by_quarter[q]["avg_score"] = round(sum(sc) / len(sc), 1) if sc else 0
        del by_quarter[q]["scores"]

    order = ["Q1", "Q2", "Q3", "Q4"]
    return sorted(by_quarter.values(), key=lambda x: order.index(x["quarter"]) if x["quarter"] in order else 99)


@router.get("/analytics/goal-distribution")
def goal_distribution(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin))
):
    goals = db.query(Goal).all()
    by_uom = {}
    by_status = {}
    for g in goals:
        by_uom[g.uom_type.value] = by_uom.get(g.uom_type.value, 0) + 1
        by_status[g.status.value] = by_status.get(g.status.value, 0) + 1
    return {"by_uom_type": by_uom, "by_status": by_status, "total": len(goals)}
