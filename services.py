from datetime import datetime
from typing import Optional
from models import UoMType, Notification, EmailNotificationLog
from sqlalchemy.orm import Session


def compute_progress_score(
    uom_type: UoMType,
    target: float,
    actual: Optional[float],
    deadline: Optional[datetime] = None,
    actual_date: Optional[datetime] = None
) -> Optional[float]:
    if actual is None:
        return None

    if uom_type == UoMType.min:
        # Higher actual = better (e.g. revenue)
        if target == 0:
            return 100.0
        return min(round((actual / target) * 100, 2), 150.0)

    elif uom_type == UoMType.max:
        # Lower actual = better (e.g. TAT, cost)
        if actual == 0:
            return 100.0
        return min(round((target / actual) * 100, 2), 150.0)

    elif uom_type == UoMType.timeline:
        if deadline is None or actual_date is None:
            return None
        if actual_date <= deadline:
            return 100.0
        # 1% penalty per day late, floor at 0
        days_late = (actual_date - deadline).days
        return round(max(0.0, 100.0 - days_late), 2)

    elif uom_type == UoMType.zero:
        return 100.0 if actual == 0 else 0.0

    return None


def create_notification(db, user_id, title, message, notif_type="info", link=None):
    notif = Notification(
        user_id=user_id,
        title=title,
        message=message,
        notif_type=notif_type,
        link=link
    )
    db.add(notif)
    db.flush()
    return notif


def get_current_quarter() -> str:
    month = datetime.utcnow().month
    if month <= 3:
        return "Q3"
    elif month <= 6:
        return "Q1"
    elif month <= 9:
        return "Q2"
    return "Q3"


def log_email_notification(db, recipient_id, subject, body, channel="email", event_type=None, status="sent"):
    log = EmailNotificationLog(
        recipient_id=recipient_id,
        subject=subject,
        body=body,
        channel=channel,
        event_type=event_type,
        status=status
    )
    db.add(log)
    db.flush()
    return log


def send_notification_with_log(db, user_id, title, message, notif_type="info", link=None, event_type=None, channels=None):
    notif = create_notification(db, user_id, title, message, notif_type, link)
    for ch in (channels or ["email"]):
        body = f"{message}\n\nNavigate to: {link or 'Portal'}"
        log_email_notification(db, user_id, title, body, channel=ch, event_type=event_type)
    return notif
