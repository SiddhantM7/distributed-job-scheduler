# Distributed Job Scheduler

A production-style distributed job scheduling platform built with **FastAPI, PostgreSQL, Docker, React, and TypeScript**.

The system provides queue-based job scheduling, retry policies, atomic job claiming, worker management, dead-letter queue handling, metrics, and a web dashboard.

---

## 📌 Project Overview

The **Distributed Job Scheduler** is designed to reliably submit, schedule, execute, monitor, retry, and recover background jobs across multiple workers.

It supports:

- Immediate, delayed, scheduled, recurring, and batch jobs
- Multiple queues and projects
- Configurable retry policies
- Idempotent job submission
- Concurrent worker processing
- Atomic job claiming using PostgreSQL row locking
- Worker heartbeats and stale-worker recovery
- Dead Letter Queue (DLQ)
- Execution history and logs
- Project-level metrics
- Real-time dashboard polling
- Dockerized deployment
- REST API with automatically generated Swagger/OpenAPI documentation

---

## 🏗️ Architecture

```text
                         ┌─────────────────────────┐
                         │      React Dashboard     │
                         │     TypeScript + Vite    │
                         └────────────┬────────────┘
                                      │
                                      │ REST / JSON
                                      ▼
                         ┌─────────────────────────┐
                         │       FastAPI API       │
                         │      Python 3.12         │
                         └────────────┬────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
                    ▼                 ▼                 ▼
              ┌───────────┐    ┌────────────┐    ┌─────────────┐
              │ Scheduler │    │   Workers  │    │  PostgreSQL │
              │  Service  │    │  Service   │    │   Database  │
              └─────┬─────┘    └──────┬─────┘    └─────────────┘
                    │                 │
                    └─────────────────┴──────────────►
                              Job Processing
```

### Main Components

| Component | Technology | Responsibility |
|---|---|---|
| API | FastAPI | REST API, authentication, authorization, business operations |
| Database | PostgreSQL 16 | Persistent job, queue, worker, execution and metrics data |
| Scheduler | Python | Promotes delayed/scheduled jobs |
| Workers | Python | Claims and executes jobs |
| Frontend | React + TypeScript | Web dashboard and workload management |
| Migrations | Alembic | Database schema migration |
| ORM/DB Layer | SQLAlchemy | Async database access and SQL operations |
| Containerization | Docker Compose | Local multi-service deployment |

---

# 🚀 Features

## Job Management

- Immediate jobs
- Delayed jobs
- One-off scheduled jobs
- Recurring cron jobs
- Batch jobs
- Job cancellation
- Manual retry
- Job filtering and pagination
- Execution history
- Execution logs
- Idempotency support

## Queue Management

- Queue creation
- Queue listing
- Queue configuration
- Queue priority
- Maximum concurrency
- Pause/resume
- Queue statistics
- Safe queue deletion

## Retry Policies

Supports:

- Fixed retry strategy
- Linear retry strategy
- Exponential retry strategy
- Configurable base delay
- Maximum delay
- Multiplier
- Maximum attempts

## Worker Management

- Worker registration
- Heartbeats
- Worker status tracking
- Worker concurrency
- Queue assignment
- Worker deregistration
- Stale-worker detection
- Stranded job recovery

## Dead Letter Queue

- DLQ listing
- Resolved/unresolved filtering
- DLQ entry details
- Retry from DLQ
- Resolve/acknowledge DLQ entries
- Payload snapshots
- Failure metadata

## Metrics

- Job status distribution
- Failure rate
- Active worker counts
- Average execution duration
- Throughput metrics
- Time windows:
  - 1 hour
  - 24 hours
  - 7 days

## Dashboard

The React dashboard provides:

- Login/Register
- Organization/project selection
- Overview dashboard
- Queue management
- Job Explorer
- Job details
- Execution history
- Worker fleet
- Dead Letter Queue
- Throughput visualization
- Live polling
- Queue pause/resume
- Job retry/cancel
- DLQ retry/resolve

---

# 📚 Implementation Phases

## Phase 1 — Foundation & Database

Implemented:

- Repository structure
- Docker Compose
- PostgreSQL 16
- Async SQLAlchemy database engine
- SQLAlchemy Core table definitions
- Alembic migrations
- Initial database schema
- PostgreSQL `pgcrypto`
- Database constraints
- Foreign keys
- Partial indexes
- Database trigger for `updated_at`

The initial migration creates the complete database foundation used by subsequent phases.

### Database Tables

The system contains:

- `users`
- `organizations`
- `organization_members`
- `projects`
- `queues`
- `retry_policies`
- `scheduled_jobs`
- `jobs`
- `job_executions`
- `job_logs`
- `workers`
- `worker_queues`
- `worker_heartbeats`
- `dead_letter_queue`
- `alembic_version`

---

## Phase 2 — Authentication + Organization/Project Management

Implemented:

- User registration
- Login
- Access tokens
- Refresh tokens
- Password hashing
- Current-user endpoint
- Organization creation
- Organization listing
- Organization membership
- Project creation
- Project listing
- Project update
- Project deletion
- Role-based authorization

### API Operations

**12 endpoints**

---

## Phase 3 — Queues + Retry Policies

Implemented:

### Queues

- Create queue
- List queues
- Queue details
- Update queue
- Pause queue
- Resume queue
- Queue statistics
- Queue deletion protection

### Retry Policies

- Create retry policy
- List retry policies
- Update retry policy
- Strategy validation
- Delay validation
- Attempt validation
- Queue/retry-policy relationship validation

### Concurrency

Atomic queue/job operations were tested using PostgreSQL locking semantics.

### API Operations

**11 endpoints**

---

## Phase 4 — Jobs + Scheduled Jobs

Implemented:

### Jobs

- Immediate jobs
- Delayed jobs
- Scheduled jobs
- Recurring jobs
- Batch jobs
- Idempotent submission
- Job listing
- Job filtering
- Job pagination
- Job details
- Execution history
- Execution logs
- Job cancellation
- Job retry

### Atomic Job Claiming

Workers use PostgreSQL:

```sql
FOR UPDATE SKIP LOCKED
```

to safely claim jobs concurrently.

The claim ordering uses:

```text
priority DESC
run_at ASC
```

This prevents multiple workers from claiming the same job.

### Scheduled Jobs

- Scheduled job listing
- Scheduled job updates
- Scheduled job deletion
- Delayed job promotion
- Scheduled job promotion

---

## Phase 5 — Worker Management

Implemented:

- Worker registration
- Worker heartbeats
- Worker status transitions
- Worker deregistration
- Queue assignment
- Queue unassignment
- Worker listing
- Worker details
- Stale-worker detection
- Stranded job recovery

Worker states include:

```text
idle
busy
draining
offline
```

Heartbeat monitoring uses a timeout-based stale-worker mechanism.

When a worker becomes stale:

```text
Worker
  ↓
offline
  ↓
Stranded jobs detected
  ↓
Jobs returned to queued state
  ↓
Another worker can claim them
```

### API Operations

**8 endpoints**

---

## Phase 6 — Dead Letter Queue

Implemented:

- DLQ listing
- DLQ filtering
- DLQ pagination
- DLQ details
- DLQ retry
- DLQ resolve
- Payload snapshots
- Failure metadata
- Retry exhaustion handling

When a job exhausts its retry attempts, it can transition:

```text
failed
  ↓
dead_letter
  ↓
Dead Letter Queue
```

The original job remains available for auditability while the DLQ stores a payload snapshot and failure information.

### API Operations

**4 endpoints**

---

## Phase 7 — Metrics + Dashboard

Implemented backend metrics:

```text
GET /api/v1/projects/{project_id}/metrics/overview
GET /api/v1/projects/{project_id}/metrics/throughput
```

Implemented frontend dashboard:

- React
- TypeScript
- Vite
- Recharts
- Authentication context
- API client
- Protected routes
- Live polling
- Project switching
- Queue views
- Job Explorer
- Worker fleet
- DLQ management
- Metrics dashboard

### API Operations

**2 endpoints**

---

# 📊 API Summary

The completed backend contains **48 API operations**.

| Area | Operations |
|---|---:|
| Authentication | 4 |
| Organizations | 5 |
| Projects | 3 |
| Queues | 8 |
| Retry Policies | 3 |
| Jobs | 11 |
| Workers | 8 |
| Dead Letter Queue | 4 |
| Metrics | 2 |
| **Total** | **48** |

---

# 📖 Swagger / OpenAPI

FastAPI automatically generates interactive API documentation.

After starting the application, open:

```text
http://localhost:8000/docs
```

The Swagger interface allows you to:

- Browse all 48 endpoints
- Expand individual operations
- Inspect request schemas
- Inspect response schemas
- Enter parameters
- Send API requests
- View response codes
- Test authenticated endpoints

Alternative OpenAPI JSON:

```text
http://localhost:8000/openapi.json
```

---

# 🖥️ Frontend Dashboard

The frontend is available at:

```text
http://localhost:5173
```

Main navigation:

```text
Register/Login
      ↓
Dashboard
      ↓
Select Organization / Project
      ↓
Overview
      ↓
Queues
      ↓
Jobs
      ↓
Workers
      ↓
Dead Letter Queue
```

The dashboard uses polling to keep workload information updated while pausing polling when the browser tab is hidden.

---

# 🗂️ Project Structure

```text
job-scheduler/
│
├── .agents/
│   └── rules/
│       └── standards.md
│
├── backend/
│   ├── app/
│   │   ├── models/
│   │   │   └── tables.py
│   │   │
│   │   ├── routers/
│   │   │   ├── auth.py
│   │   │   ├── organizations.py
│   │   │   ├── projects.py
│   │   │   ├── queues.py
│   │   │   ├── retry_policies.py
│   │   │   ├── jobs.py
│   │   │   ├── workers.py
│   │   │   ├── dlq.py
│   │   │   └── metrics.py
│   │   │
│   │   ├── schemas/
│   │   │   ├── auth.py
│   │   │   ├── organizations.py
│   │   │   ├── projects.py
│   │   │   ├── queues.py
│   │   │   ├── retry_policies.py
│   │   │   ├── jobs.py
│   │   │   ├── workers.py
│   │   │   ├── dlq.py
│   │   │   └── metrics.py
│   │   │
│   │   ├── services/
│   │   │   ├── auth.py
│   │   │   ├── jobs.py
│   │   │   ├── workers.py
│   │   │   ├── dlq.py
│   │   │   └── metrics.py
│   │   │
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── dependencies.py
│   │   └── main.py
│   │
│   ├── migrations/
│   │   ├── versions/
│   │   │   └── 001_initial_schema.py
│   │   ├── env.py
│   │   └── script.py.mako
│   │
│   ├── scheduler/
│   │   └── main.py
│   │
│   ├── workers/
│   │   └── main.py
│   │
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_atomic_claim.py
│   │   ├── test_jobs.py
│   │   ├── test_queues.py
│   │   ├── test_retry_policies.py
│   │   ├── test_workers.py
│   │   ├── test_dlq.py
│   │   └── test_metrics.py
│   │
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   └── pytest.ini
│
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.ts
│   │   │   └── types.ts
│   │   │
│   │   ├── components/
│   │   │   ├── Layout.tsx
│   │   │   └── StatusBadge.tsx
│   │   │
│   │   ├── context/
│   │   │   └── AuthContext.tsx
│   │   │
│   │   ├── hooks/
│   │   │   └── usePolling.ts
│   │   │
│   │   ├── pages/
│   │   │   ├── Login.tsx
│   │   │   ├── Register.tsx
│   │   │   ├── Overview.tsx
│   │   │   ├── Queues.tsx
│   │   │   ├── QueueDetail.tsx
│   │   │   ├── Jobs.tsx
│   │   │   ├── JobDetail.tsx
│   │   │   ├── Workers.tsx
│   │   │   └── DLQ.tsx
│   │   │
│   │   ├── App.tsx
│   │   └── main.tsx
│   │
│   ├── package.json
│   ├── package-lock.json
│   ├── Dockerfile
│   ├── vite.config.ts
│   └── tsconfig.json
│
├── docs/
│   ├── api-spec.md
│   ├── database-design.md
│   ├── architecture.md
│   └── schema.sql
│
├── .env.example
├── .gitignore
└── docker-compose.yml
```

---

# 🐳 Running the Project with Docker

## Prerequisites

Install:

- Docker Desktop
- Git
- Node.js/npm (only required for local frontend development)

Verify Docker:

```powershell
docker --version
docker compose version
```

---

## 1. Clone the Repository

```bash
git clone https://github.com/SiddhantM7/distributed-job-scheduler.git
cd distributed-job-scheduler
```

---

## 2. Configure Environment Variables

Create a `.env` file based on:

```text
.env.example
```

For example:

```env
POSTGRES_USER=jobscheduler
POSTGRES_PASSWORD=your_password
POSTGRES_DB=jobscheduler
```

Do not commit `.env` to Git.

---

## 3. Build and Start the System

```powershell
docker compose build
docker compose up -d
```

Check service status:

```powershell
docker compose ps
```

Expected services:

```text
api
postgres
scheduler
worker
frontend
```

---

# 🔍 Verify the Backend

Check API logs:

```powershell
docker compose logs api --tail=50
```

Expected startup includes:

```text
Uvicorn running on http://0.0.0.0:8000
Application startup complete.
```

---

# 🗄️ Verify PostgreSQL

Check database health:

```powershell
docker compose ps
```

PostgreSQL should show:

```text
Up ... (healthy)
```

List database tables:

```powershell
docker compose exec postgres psql -U jobscheduler -d jobscheduler -c "\dt"
```

---

# 🔄 Verify Database Migration

The API container automatically executes:

```bash
alembic upgrade head
```

during startup.

Check migration status:

```powershell
docker compose exec api alembic current
```

---

# 🧪 Run Tests

Run the complete test suite:

```powershell
docker compose exec api pytest -v
```

Current verification:

```text
78 passed
1 warning
```

The test suite covers:

- Authentication
- Organizations/projects
- Queue operations
- Retry policies
- Job creation
- Idempotency
- Atomic job claiming
- Scheduled jobs
- Worker management
- Worker recovery
- DLQ
- Metrics
- Authorization
- Validation
- Failure scenarios

---

# 🎨 Frontend Development

The frontend can also be run locally.

```powershell
cd frontend
npm install
npm run build
```

Production build verification:

```text
✓ TypeScript compilation
✓ Vite production build
```

The generated production files are placed in:

```text
frontend/dist/
```

When using Docker Compose, the frontend is available at:

```text
http://localhost:5173
```

---

# 🔐 Security Considerations

The project includes:

- Password hashing
- JWT-based authentication
- Access and refresh tokens
- Role-based authorization
- Organization tenancy boundaries
- Project-level authorization
- Queue-level authorization
- Worker ownership checks
- Protected management operations
- `.env` exclusion through `.gitignore`

Secrets should be supplied through environment variables rather than committed to source control.

---

# ⚙️ Important Technical Concepts

## Atomic Job Claiming

The worker uses PostgreSQL row locking:

```sql
FOR UPDATE SKIP LOCKED
```

This enables multiple workers to safely compete for queued jobs without duplicate claims.

---

## Idempotency

Job submission supports an idempotency key.

Conceptually:

```text
First request
     ↓
Job created
     ↓
201 Created

Same request + same key
     ↓
Existing job returned
     ↓
200 OK

Same key + different payload
     ↓
409 Conflict
```

---

## Retry Flow

```text
Job
 ↓
Execution
 ↓
Success ───────────────► Completed
 │
Failure
 ↓
Attempts remaining?
 ├── Yes ──► Retry policy ──► Scheduled
 │
 └── No ───► Dead Letter Queue
```

---

## Worker Recovery

```text
Worker registered
      ↓
Heartbeat every 10 seconds
      ↓
Worker becomes unavailable
      ↓
Heartbeat timeout
      ↓
Worker marked offline
      ↓
Stranded jobs released
      ↓
Jobs become queued
      ↓
Another worker claims them
```

---

# 📈 Metrics

The metrics API provides project-level aggregation.

### Overview

```text
GET /api/v1/projects/{project_id}/metrics/overview
```

Provides:

- Total jobs
- Job status counts
- Failure rate
- Active workers
- Average duration

### Throughput

```text
GET /api/v1/projects/{project_id}/metrics/throughput
```

Supported windows:

```text
1h   → 5-minute buckets
24h  → 1-hour buckets
7d   → 1-day buckets
```

---

# 🧰 Technology Stack

### Backend

- Python 3.12
- FastAPI
- Pydantic
- SQLAlchemy
- asyncpg
- Alembic
- PostgreSQL 16
- PyJWT
- Passlib
- croniter
- pytest
- pytest-asyncio

### Frontend

- React
- TypeScript
- Vite
- Recharts

### Infrastructure

- Docker
- Docker Compose
- PostgreSQL

---

# 📋 Project Verification Status

| Component | Status |
|---|---|
| Database schema | ✅ Complete |
| Alembic migration | ✅ Complete |
| Authentication | ✅ Complete |
| Organizations | ✅ Complete |
| Projects | ✅ Complete |
| Queues | ✅ Complete |
| Retry policies | ✅ Complete |
| Jobs | ✅ Complete |
| Scheduled jobs | ✅ Complete |
| Atomic claiming | ✅ Complete |
| Worker management | ✅ Complete |
| Worker recovery | ✅ Complete |
| Dead Letter Queue | ✅ Complete |
| Metrics | ✅ Complete |
| React dashboard | ✅ Complete |
| Swagger/OpenAPI | ✅ 48 operations |
| Backend tests | ✅ 78 passed |
| Frontend build | ✅ Successful |
| Docker deployment | ✅ Successful |

---

# 🌐 Repository

GitHub:

https://github.com/SiddhantM7/distributed-job-scheduler

---

# 🎯 Future Improvements

Possible future extensions include:

- Redis-based distributed coordination
- More sophisticated worker autoscaling
- Kubernetes deployment
- Distributed tracing
- Prometheus/Grafana integration
- WebSocket-based live dashboard updates
- Advanced scheduling rules
- Job dependency graphs
- Multi-region workers
- Role/permission expansion
- Production secret management
- Horizontal API scaling

---

# 📄 License

This project was developed as an academic/software engineering project.

Add an explicit open-source license here if the project is intended to be distributed publicly.

---

## 👨‍💻 Project Status

**Distributed Job Scheduler — Phases 1–7 Complete**

```text
Foundation
    ↓
Authentication & Projects
    ↓
Queues & Retry Policies
    ↓
Jobs & Scheduling
    ↓
Worker Management
    ↓
Dead Letter Queue
    ↓
Metrics & Dashboard
    ↓
Dockerized Application
    ↓
78 Automated Tests
```

**48 API operations · 78 passing tests · Full React dashboard · Dockerized deployment**
