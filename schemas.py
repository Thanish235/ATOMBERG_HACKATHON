from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime
from models import UserRole, GoalStatus, UoMType, CheckinStatus


class Token(BaseModel):
    access_token: str
    token_type: str
    user: "UserOut"

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: UserRole = UserRole.employee
    department: Optional[str] = None
    manager_id: Optional[int] = None


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: UserRole
    department: Optional[str]
    manager_id: Optional[int]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserOutWithTeam(UserOut):
    direct_reports: List["UserOut"] = []
    manager: Optional["UserOut"] = None

    class Config:
        from_attributes = True


class GoalCreate(BaseModel):
    thrust_area: str
    title: str
    description: Optional[str] = None
    uom_type: UoMType
    target: float
    deadline: Optional[datetime] = None
    weightage: float

    @field_validator("weightage")
    @classmethod
    def validate_weightage(cls, v):
        if v < 10:
            raise ValueError("Minimum weightage per goal is 10%")
        if v > 100:
            raise ValueError("Maximum weightage per goal is 100%")
        return v

    @field_validator("target")
    @classmethod
    def validate_target(cls, v):
        if v < 0:
            raise ValueError("Target must be non-negative")
        return v


class GoalUpdate(BaseModel):
    thrust_area: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    uom_type: Optional[UoMType] = None
    target: Optional[float] = None
    deadline: Optional[datetime] = None
    weightage: Optional[float] = None
    manager_comment: Optional[str] = None


class SharedGoalPush(BaseModel):
    goal_id: int
    employee_ids: List[int]


class GoalOut(BaseModel):
    id: int
    owner_id: int
    owner: Optional[UserOut] = None
    parent_goal_id: Optional[int]
    thrust_area: str
    title: str
    description: Optional[str]
    uom_type: UoMType
    target: float
    deadline: Optional[datetime]
    weightage: float
    status: GoalStatus
    is_shared: bool
    is_locked: bool
    manager_comment: Optional[str]
    created_at: datetime
    updated_at: datetime
    checkins: List["CheckinOut"] = []

    class Config:
        from_attributes = True


class CheckinCreate(BaseModel):
    quarter: str
    actual_achievement: Optional[float] = None
    actual_date: Optional[datetime] = None
    status: CheckinStatus = CheckinStatus.not_started


class CheckinManagerUpdate(BaseModel):
    manager_comment: str


class CheckinOut(BaseModel):
    id: int
    goal_id: int
    quarter: str
    actual_achievement: Optional[float]
    actual_date: Optional[datetime]
    status: CheckinStatus
    manager_comment: Optional[str]
    progress_score: Optional[float]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AuditLogOut(BaseModel):
    id: int
    goal_id: int
    changed_by_id: int
    changed_by: Optional[UserOut] = None
    field_changed: str
    old_value: Optional[str]
    new_value: Optional[str]
    changed_at: datetime
    note: Optional[str]

    class Config:
        from_attributes = True


class NotificationOut(BaseModel):
    id: int
    title: str
    message: str
    is_read: bool
    notif_type: str
    link: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class AchievementReportRow(BaseModel):
    employee_name: str
    employee_email: str
    department: Optional[str]
    goal_title: str
    thrust_area: str
    uom_type: str
    target: float
    quarter: str
    actual: Optional[float]
    progress_score: Optional[float]
    status: str


class DashboardStats(BaseModel):
    total_employees: int
    goals_submitted: int
    goals_approved: int
    checkins_completed: int
    completion_rate: float
    dept_breakdown: List[dict]


Token.model_rebuild()
UserOutWithTeam.model_rebuild()
GoalOut.model_rebuild()


class EscalationRuleCreate(BaseModel):
    name: str
    rule_type: str
    trigger_days: int = 7
    is_active: bool = True


class EscalationRuleOut(BaseModel):
    id: int
    name: str
    rule_type: str
    trigger_days: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class EscalationLogOut(BaseModel):
    id: int
    rule_id: int
    user_id: int
    level: int
    status: str
    message: str
    created_at: datetime
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


class EmailLogOut(BaseModel):
    id: int
    recipient_id: int
    subject: str
    body: str
    channel: str
    status: str
    event_type: Optional[str]
    sent_at: datetime

    class Config:
        from_attributes = True


class EmailSettingsUpdate(BaseModel):
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    teams_webhook_url: Optional[str] = None
    notify_on_submission: bool = True
    notify_on_approval: bool = True
    notify_on_rejection: bool = True
    notify_on_checkin: bool = True
