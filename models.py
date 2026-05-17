from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text, Enum as SAEnum
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
import enum

Base = declarative_base()


class UserRole(str, enum.Enum):
    employee = "employee"
    manager = "manager"
    admin = "admin"


class GoalStatus(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"
    approved = "approved"
    returned = "returned"


class UoMType(str, enum.Enum):
    min = "min"         # higher is better (e.g. sales revenue)
    max = "max"         # lower is better (e.g. TAT)
    timeline = "timeline"
    zero = "zero"       # zero = success


class CheckinStatus(str, enum.Enum):
    not_started = "not_started"
    on_track = "on_track"
    completed = "completed"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.employee)
    department = Column(String, nullable=True)
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    manager = relationship("User", remote_side=[id], backref="direct_reports")
    goals = relationship("Goal", back_populates="owner", foreign_keys="Goal.owner_id")
    notifications = relationship("Notification", back_populates="user")


class Goal(Base):
    __tablename__ = "goals"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    parent_goal_id = Column(Integer, ForeignKey("goals.id"), nullable=True)  # for shared goals
    thrust_area = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    uom_type = Column(SAEnum(UoMType), nullable=False)
    target = Column(Float, nullable=False)
    deadline = Column(DateTime, nullable=True)  # used for timeline type
    weightage = Column(Float, nullable=False)
    status = Column(SAEnum(GoalStatus), default=GoalStatus.draft)
    is_shared = Column(Boolean, default=False)
    is_locked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    manager_comment = Column(Text, nullable=True)

    owner = relationship("User", back_populates="goals", foreign_keys=[owner_id])
    checkins = relationship("Checkin", back_populates="goal")
    audit_logs = relationship("AuditLog", back_populates="goal")
    parent_goal = relationship("Goal", remote_side=[id], backref="shared_copies")


class Checkin(Base):
    __tablename__ = "checkins"
    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, ForeignKey("goals.id"), nullable=False)
    quarter = Column(String, nullable=False)  # Q1, Q2, Q3, Q4
    actual_achievement = Column(Float, nullable=True)
    actual_date = Column(DateTime, nullable=True)  # for timeline UoM
    status = Column(SAEnum(CheckinStatus), default=CheckinStatus.not_started)
    manager_comment = Column(Text, nullable=True)
    progress_score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    goal = relationship("Goal", back_populates="checkins")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, ForeignKey("goals.id"), nullable=False)
    changed_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    field_changed = Column(String, nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    changed_at = Column(DateTime, default=datetime.utcnow)
    note = Column(Text, nullable=True)

    goal = relationship("Goal", back_populates="audit_logs")
    changed_by = relationship("User")


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    notif_type = Column(String, default="info")  # info, warning, success, action
    link = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="notifications")


class EscalationRule(Base):
    __tablename__ = "escalation_rules"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    rule_type = Column(String, nullable=False)  # goal_not_submitted, goal_not_approved, checkin_not_done
    trigger_days = Column(Integer, nullable=False, default=7)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    logs = relationship("EscalationLog", back_populates="rule")


class EscalationLog(Base):
    __tablename__ = "escalation_logs"
    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("escalation_rules.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    level = Column(Integer, default=1)    # 1=employee, 2=manager, 3=HR/skip-level
    status = Column(String, default="open")  # open, resolved
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    rule = relationship("EscalationRule", back_populates="logs")
    user = relationship("User")


class EmailNotificationLog(Base):
    __tablename__ = "email_notification_logs"
    id = Column(Integer, primary_key=True, index=True)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    channel = Column(String, default="email")  # email, teams
    status = Column(String, default="sent")    # sent, failed, pending
    event_type = Column(String, nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow)

    recipient = relationship("User")
