# ⬡ AtomQuest — Goal Setting & Tracking Portal
### AtomQuest Hackathon 1.0 Submission

A full-stack, single-server web portal for employee goal setting, manager approval, quarterly check-ins, and performance analytics.

---

## 🚀 Quick Start (Local)

```bash
# Clone and enter the project
git clone <your-repo-url>
cd Atomberg_enhanced

# Run everything (installs deps + starts server)
bash run.sh
```

Open **http://localhost:8000** in your browser.

> API docs available at **http://localhost:8000/docs**

---

## 🔑 Login Credentials

| Role | Email | Password |
|------|-------|----------|
| **Admin / HR** | admin@atomquest.com | admin123 |
| **Manager (L1)** | manager@atomquest.com | manager123 |
| **Employee** | employee@atomquest.com | employee123 |

Additional seeded employees: `sneha@atomquest.com` / `ravi@atomquest.com` (password: `employee123`)

---

## 🏗️ Architecture

```
Browser (Vanilla JS SPA)
        │  HTTPS + Bearer JWT
        ▼
FastAPI (Uvicorn ASGI)  ←─ main.py · routers.py · auth.py · services.py
        │
        ▼
SQLAlchemy ORM  →  SQLite (atomquest.db)
```

See `AtomQuest_Architecture.pdf` for the full layered diagram.

**Tech Stack:**
- **Backend:** Python 3.12, FastAPI 0.115, Uvicorn
- **Database:** SQLite via SQLAlchemy 2.0 ORM
- **Auth:** JWT (python-jose), bcrypt password hashing
- **Frontend:** Single-file Vanilla JS SPA (`index.html`) — no build step required

---

## ✅ Features Implemented

### Phase 1 — Goal Creation & Approval (Must-Have)
- [x] Employee goal creation with Thrust Area, UoM, Target, Weightage
- [x] Validation: total weightage = 100%, min 10% per goal, max 8 goals
- [x] Manager (L1) approval workflow — review, approve, or return with comment
- [x] Goal lock on approval; Admin unlock with full audit trail
- [x] Shared goals — manager pushes departmental KPI; recipients adjust weightage only

### Phase 2 — Achievement Tracking & Check-ins (Must-Have)
- [x] Quarterly check-in (Q1–Q4) with actual achievement entry
- [x] Status per goal: Not Started / On Track / Completed
- [x] Manager check-in comments per quarter
- [x] Auto-computed progress scores for all 4 UoM types:
  - **Min** (higher is better): `achievement ÷ target`
  - **Max** (lower is better): `target ÷ achievement`
  - **Timeline**: completion date vs. deadline
  - **Zero**: 100% if 0, else 0%

### Reporting & Governance
- [x] Achievement report — CSV export (Planned vs. Actual for all employees)
- [x] Completion dashboard — real-time check-in status by employee/manager
- [x] Audit trail — every post-lock change logged with who/what/when

### Bonus Features
- [x] **Escalation Module (§5.3)** — configurable rules, escalation engine, resolution workflow
- [x] **Analytics Dashboard (§5.4)** — QoQ trends, dept heatmap, thrust area breakdown, manager effectiveness
- [x] **Email/Teams Integration (§5.2)** — notification log, settings UI, simulated dispatch (logged to DB)

---

## 📁 Project Structure

```
Atomberg_enhanced/
├── main.py          # FastAPI app, startup seed, auth endpoints
├── routers.py       # All API routes (goals, checkins, reports, analytics, escalation)
├── models.py        # SQLAlchemy models (User, Goal, Checkin, AuditLog, Notification, Escalation)
├── schemas.py       # Pydantic request/response schemas
├── services.py      # Progress score computation, notification helpers
├── auth.py          # JWT creation/validation, password hashing, role guards
├── database.py      # SQLite engine, session factory, schema init
├── index.html       # Complete single-page frontend (2500+ lines)
├── requirements.txt # Python dependencies
└── run.sh           # One-command startup script
```

---

## ☁️ Deploying to Railway

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
3. Select this repo
4. Railway auto-detects Python. Set the start command:
   ```
   uvicorn main:app --host 0.0.0.0 --port $PORT
   ```
5. Click **Deploy** — your live URL appears in ~2 minutes

## ☁️ Deploying to Render

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → **New Web Service**
3. Connect your GitHub repo
4. Set:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Click **Create Web Service**

---

## 📋 Submission Checklist

- [x] Live demo URL (see submission form)
- [x] Source code repository (this repo)
- [x] Architecture diagram — `AtomQuest_Architecture.pdf`
- [x] Login credentials for all 3 roles (see table above)
