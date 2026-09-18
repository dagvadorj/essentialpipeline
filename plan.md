# EssentialPipeline - Implementation Plan

## Status Summary

**Working end-to-end today**: user registration/login (JWT), project CRUD with zip upload and versioning (API and web UI), the web dashboard, the Flask-Admin governance panel, and Alembic migrations validated against MySQL. All 32 data models across the governance/execution/monitoring/deployment layers are implemented.

**Implemented but not wired to anything**: the Docker execution wrapper (`utils/docker.py`) and the APScheduler-based task scheduler (`services/scheduler.py`) are both functionally complete on their own, but nothing in the running application calls them - no route triggers a task run, and `schedule_all_tasks()` is never called at startup.

**Not started**: Garage integration (project files currently live on local disk only), security scanning (bandit/safety are listed as dependencies but not called from anywhere), ML model execution, the deployment/approval workflow, monitoring/alerting, rate limiting, API documentation, and automated tests. No git repository has been initialized yet.

**Two open contradictions between a recorded decision and the actual code**, to resolve before building further on either:
- **Storage** (Decision 4): committed to Garage; `utils/storage.py` only writes to local disk, and `services/scheduler.py` has a comment acknowledging the Garage copy step is skipped.
- **Task orchestration** (Decision 5): committed to a linear pipeline, DAG deferred; `services/scheduler.py` already implements dependency-graph execution against the `TaskDependency` model (`execute_task` skips on unmet dependencies, `trigger_dependent_tasks` cascades on success). That logic predates the decision and needs to be simplified to match it, or the decision needs revisiting now that the DAG logic already exists.

Checkboxes in this document track real implementation status, not aspiration - update them as work lands.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                Web UI Layer (Flask + Jinja2, server-rendered)         │
├─────────────────────────────────────────────────────────────────────┤
│  User Dashboard    Project CRUD/Upload    Task/Deployment/Log Views   │
│  Admin Panel (Flask-Admin: groups, connections, audit logs, etc.)     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         API Layer (REST/Flask)                        │
├─────────────────────────────────────────────────────────────────────┤
│  ML Model Execution API         Pipeline Trigger API                   │
│  Status Query API               Audit Log API                          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Monitoring Layer                                 │
├─────────────────────────────────────────────────────────────────────┤
│  Deployment Logs    Security Parsing Logs    Execution Logs           │
│  Metrics Collection  Alerting System        Log Aggregation          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Execution Layer                                │
├─────────────────────────────────────────────────────────────────────┤
│  Project Upload    Security Parsing    Dependency Caching    Scheduler  │
│  Isolated Execution  ML Model Storage   Env Promotion (Dev→QA→Prod)    │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Governance Layer                               │
├─────────────────────────────────────────────────────────────────────┤
│  User Groups    DB/Storage Connections    Clearance Mappings          │
│  Environment Designations    Audit Logs    Access Control              │
└─────────────────────────────────────────────────────────────────────┘
```

The arrows show conceptual layering, not literal call order. In the actual implementation, the Web UI and the REST API are two independent presentation surfaces that both query the Governance/Execution/Monitoring models directly - the UI does not proxy through the API - plus a third surface (Flask-Admin) for raw governance-table CRUD.

---

## Decisions

### 1. Isolation: Docker
Each uploaded project runs in its own container. Rejected virtualenv (too little isolation) and Kubernetes (unnecessary at current scale).
Status: container lifecycle implemented in `utils/docker.py` (create/start/stop/execute/logs/cleanup); not yet triggered by any route.

### 2. Scheduler: APScheduler, not Celery/Redis
Implemented with APScheduler + a `ThreadPoolExecutor` instead of Celery/Redis - one less moving piece (no message broker) at the current scale. Revisit if concurrency needs outgrow a single process.
Status: implemented in `services/scheduler.py`; not yet invoked from app startup or any route (see Status Summary).

### 3. Auth: JWT (Flask-JWT-Extended)
Stateless, standard fit for a REST API.
Status: implemented for the API. The web UI reuses the same `@jwt_required()` decorator, which expects a bearer header - there is no login page or cookie/session bridge, so the web UI cannot currently be reached from a plain browser without manually attaching a token.

### 4. Storage: Garage for files, MySQL for metadata
Keeps large binary files (project archives, model artifacts, logs) out of the relational database.
Status: not implemented. `utils/storage.py` writes only to local disk under `UPLOAD_FOLDER`. Needs either real Garage client work or a decision to stay on local disk for now.

### 5. Task orchestration: linear pipeline, DAG deferred
Sequential task execution (`Task.sequence_order`, not yet added to the model) instead of a dependency graph, cycle detection, and topological sort, until there's a proven need for it.
Status: contradicted by existing code - `services/scheduler.py` already implements DAG-style dependency execution against `TaskDependency`. Needs reconciling: simplify the scheduler to match this decision, or revisit the decision.

### 6. Security scanning: dependency scan blocks, static/AST scan doesn't
Docker isolation covers container/host escape, so a blocking static-analysis gate on top of that is mostly false-positive friction. Dependency vulnerability scanning (Safety) still blocks, since a running project is granted real DB/storage credentials. Bandit findings are audit-only.
Status: neither is implemented - both are listed in `requirements.txt` but not called from any service.

### 7. Web UI: server-rendered Flask + Jinja2, no htmx/SPA
Plain links/forms with full page reloads. No separate build pipeline or client-side framework; a genuinely-needed dynamic refresh later gets a small hand-written `fetch()` call instead of a library.
Status: dashboard, project pages, and the Flask-Admin panel work this way today. Blocked from real use by the login gap in Decision 3.

---

## Progress by Layer

### Governance
- [x] Models: `User`, `Group`, `Permission`, `Environment`, `DatabaseConnection`, `StorageConnection`, `GroupConnectionClearance`, `AuditLog`
- [x] Connection-string encryption (`utils/security.py`, Fernet)
- [x] Audit logging middleware (best-effort, non-blocking)
- [ ] Governance API/UI: groups, permissions, environments, connections, clearances CRUD (`admin_governance` route and its API equivalents are stubs)
- [ ] Connection health-check endpoint / connection testing utility
- [ ] Environment promotion state machine (`Deployment.status` models the states; no service logic drives transitions)
- [ ] Audit log query API (currently only visible via Flask-Admin)

### Execution
- [x] Models: `Project`, `ProjectVersion`, `ProjectFile`, `SecurityParseResult`, `SecurityFinding`, `Dependency`, `DependencyCache`, `ExecutionEnvironment`
- [x] Project CRUD + zip upload + versioning, both API and web UI
- [x] Docker container lifecycle (`utils/docker.py`) - not yet triggered by anything (see Decision 1)
- [ ] File storage on Garage (currently local disk - Decision 4)
- [ ] Uploaded zip is unpacked/validated (currently stored as-is, contents never inspected)
- [ ] Dependency extraction/caching from a project's `requirements.txt`
- [ ] Security scanning wired up (Decision 6)

### Web UI
- [x] Base layout + navigation
- [x] Dashboard (stats computed on page load; the `/user/stats` JSON endpoint exists but is currently unused)
- [x] Project pages: list, create, detail, edit, upload, delete
- [x] Admin panel via Flask-Admin: Users, Groups, Permissions, Environments, DB/Storage Connections, Audit Logs, Projects, Tasks, ML Models
- [ ] Task pages (stub, redirects to dashboard)
- [ ] Deployment pages (stub)
- [ ] Log viewer pages (stub)
- [ ] Login page / session bridge (Decision 3 - blocks real browser use of everything above)

### Scheduling & Deployment
- [x] Models: `Task`, `TaskRun`, `TaskDependency`, `MLModel`, `MLModelVersion`, `MLModelExecution`, `Deployment`, `Approval`
- [x] Scheduler service written (`services/scheduler.py`) - not wired in; implements DAG dependency logic that contradicts Decision 5
- [ ] `Task.sequence_order` column + linear execution (replaces the DAG-dependency logic once reconciled)
- [ ] A task can actually be triggered from the API or UI (currently creating a task only inserts a row - nothing runs it)
- [ ] ML model artifact upload/download, model execution service
- [ ] Environment promotion workflow / approval state machine / rollback

### Monitoring
- [x] Models: `DeploymentLog`, `SecurityLog`, `ExecutionLog`, `SystemMetric`, `Alert`, `AlertRule`
- [x] Health check endpoints (`/health`, `/api/v1/health`)
- [ ] Structured/centralized logging service (currently ad hoc `logging` calls)
- [ ] Log aggregation, querying, export (`api/v1/logs` is a stub)
- [ ] System metrics collection (model exists, nothing populates it)
- [ ] Alerting (email/Slack)

### API Layer
- [x] JWT authentication (register/login/refresh/logout/me/list-users/password change)
- [x] Project endpoints (CRUD, upload, versions, task creation)
- [ ] Task/model/deployment/log endpoints (currently 501 stubs)
- [ ] RBAC applied to routes (`admin_required`/`project_access_required` exist in `middleware/` but aren't used anywhere yet)
- [ ] Rate limiting
- [ ] Request/response schema validation
- [ ] OpenAPI/Swagger documentation

### Foundation
- [x] Flask/SQLAlchemy application factory, dependency set fixed and installable in a clean venv
- [x] Alembic initialized; initial migration generated and validated against MySQL
- [x] `.env`/config wired to real values (DB host, JWT/encryption secrets)
- [ ] Git repository initialized

### Testing & Deployment
- [ ] Automated tests (none exist)
- [ ] CI pipeline
- [ ] Dockerfile for the app itself (distinct from `utils/docker.py`, which containerizes *uploaded projects*, not this app)

---

## Directory Structure

```
essentialdata/
├── run.py                       # Entry point
├── requirements.txt
├── alembic.ini
├── .env / .env.example
│
├── essentialpipeline/            # Main package
│   ├── __init__.py               # db, jwt, admin extension instances
│   ├── config/__init__.py
│   ├── app/
│   │   ├── __init__.py           # create_app() factory
│   │   ├── admin_setup.py        # Flask-Admin configuration
│   │   ├── middleware/
│   │   └── routes/
│   │       ├── api/v1/           # auth, projects (real); tasks, models, deployments, logs (stubs)
│   │       ├── user/             # dashboard, projects (real); tasks, models, deployments, logs (stubs)
│   │       └── admin/            # governance, monitoring (stubs)
│   ├── models/
│   │   ├── governance.py
│   │   ├── execution.py
│   │   ├── monitoring.py
│   │   └── deployment.py
│   ├── services/
│   │   └── scheduler.py          # implemented, not yet wired to any route
│   ├── utils/
│   │   ├── security.py           # encryption, password hashing
│   │   ├── storage.py            # local-disk file storage (not Garage)
│   │   └── docker.py             # container lifecycle, not yet wired to any route
│   └── templates/
│       ├── base.html, user/, admin/
│
├── migrations/                   # Alembic
│   ├── env.py
│   └── versions/
│
├── scripts/
│   └── seed_data.py
│
└── static/
    ├── css/style.css
    └── js/app.js
```

---

## Technology Stack

### Core Framework
- **Web Framework**: Flask 3.0.0
- **ORM**: SQLAlchemy 2.0.36
- **Database**: MySQL (via mysql-connector-python 8.3.0)

### Execution Engine
- **Scheduler**: APScheduler 3.10.4 with a `ThreadPoolExecutor` (Decision 2)
- **Containerization**: Docker 7.0.0 (`docker` Python SDK)

### Storage
- **Primary**: MySQL (metadata)
- **Object Storage**: Garage, decided but not implemented (Decision 4) - local disk today

### Web UI
- **Templating**: Jinja2 (Flask's built-in engine), Bootstrap for styling
- **Interactivity**: plain links/forms with full page reloads, no htmx or JS framework (Decision 7)
- **Admin panel**: Flask-Admin 1.6.1

### Security
- **Authentication**: Flask-JWT-Extended 4.5.3
- **Encryption**: Cryptography 42.0.0 (Fernet, for connection strings)
- **Scanning**: Safety 2.3.5 (blocking gate), Bandit 1.7.7 (audit/warning only) - neither wired up yet (Decision 6)

### Monitoring
- **Metrics**: not yet chosen/implemented
- **Logging**: Python's `logging` module, ad hoc

---

## Database Schema Design

### Core Tables (Governance)

```sql
-- Users (existing, extend)
ALTER TABLE users ADD COLUMN group_id INT;
ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN last_login DATETIME;

-- Groups
CREATE TABLE groups (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(80) UNIQUE NOT NULL,
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Permissions
CREATE TABLE permissions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(80) UNIQUE NOT NULL,
    resource_type VARCHAR(50) NOT NULL,  -- 'database', 'storage', 'project', etc.
    action VARCHAR(50) NOT NULL,          -- 'read', 'write', 'admin', 'execute'
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- User-Group many-to-many
CREATE TABLE user_groups (
    user_id INT NOT NULL,
    group_id INT NOT NULL,
    PRIMARY KEY (user_id, group_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
);

-- Group-Permission many-to-many
CREATE TABLE group_permissions (
    group_id INT NOT NULL,
    permission_id INT NOT NULL,
    PRIMARY KEY (group_id, permission_id),
    FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE,
    FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE
);

-- Environments
CREATE TABLE environments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,      -- 'dev', 'qa', 'prod'
    description TEXT,
    is_production BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Database Connections
CREATE TABLE database_connections (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(80) NOT NULL,
    connection_string_encrypted TEXT NOT NULL,
    connection_type VARCHAR(50) NOT NULL,  -- 'mysql', 'postgresql', etc.
    environment_id INT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (environment_id) REFERENCES environments(id)
);

-- Storage Connections (Garage)
CREATE TABLE storage_connections (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(80) NOT NULL,
    endpoint VARCHAR(255) NOT NULL,
    bucket VARCHAR(80) NOT NULL,
    credentials_encrypted TEXT NOT NULL,
    environment_id INT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (environment_id) REFERENCES environments(id)
);

-- Group Connection Clearance (connection_id is polymorphic - see note below)
CREATE TABLE group_connection_clearances (
    id INT AUTO_INCREMENT PRIMARY KEY,
    group_id INT NOT NULL,
    connection_type ENUM('database', 'storage') NOT NULL,
    connection_id INT NOT NULL,  -- references database_connections.id or storage_connections.id depending on connection_type; not a real FK, resolved in application code
    access_level ENUM('none', 'read', 'write', 'admin') DEFAULT 'none',
    FOREIGN KEY (group_id) REFERENCES groups(id)
);
```

### Execution Tables

```sql
-- Projects
CREATE TABLE projects (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    owner_user_id INT NOT NULL,
    current_version_id INT,
    storage_path VARCHAR(512) NOT NULL,  -- Path to project files
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_user_id) REFERENCES users(id),
    FOREIGN KEY (current_version_id) REFERENCES project_versions(id)
);

-- Project Versions
CREATE TABLE project_versions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL,
    version VARCHAR(50) NOT NULL,  -- e.g., '1.0.0'
    changelog TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

-- Project Files
CREATE TABLE project_files (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_version_id INT NOT NULL,
    file_path VARCHAR(512) NOT NULL,  -- Path within project
    file_size INT,
    file_hash VARCHAR(64),  -- SHA-256
    storage_path VARCHAR(512),  -- Path in object storage
    FOREIGN KEY (project_version_id) REFERENCES project_versions(id)
);

-- Security Parse Results
CREATE TABLE security_parse_results (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_version_id INT NOT NULL,
    parser_version VARCHAR(50),
    overall_status ENUM('passed', 'warning', 'failed') DEFAULT 'passed',  -- 'warning' = AST/bandit findings (non-blocking), 'failed' = vulnerable dependency (blocks execution)
    parsed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_version_id) REFERENCES project_versions(id)
);

-- Security Findings
CREATE TABLE security_findings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    parse_result_id INT NOT NULL,
    severity ENUM('low', 'medium', 'high', 'critical') DEFAULT 'medium',
    finding_type VARCHAR(50) NOT NULL,  -- 'import', 'dependency', 'code_pattern'
    description TEXT NOT NULL,
    file_path VARCHAR(512),
    line_number INT,
    code_snippet TEXT,
    recommendation TEXT,
    FOREIGN KEY (parse_result_id) REFERENCES security_parse_results(id)
);

-- Dependencies
CREATE TABLE dependencies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_version_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    version_spec VARCHAR(255) NOT NULL,  -- e.g., '==1.0.0', '>=2.0'
    resolved_version VARCHAR(50),  -- Actual installed version
    FOREIGN KEY (project_version_id) REFERENCES project_versions(id)
);

-- Dependency Cache
CREATE TABLE dependency_cache (
    id INT AUTO_INCREMENT PRIMARY KEY,
    dependency_id INT NOT NULL,
    cache_path VARCHAR(512) NOT NULL,  -- Path to cached package
    cache_size INT,
    cache_hash VARCHAR(64),
    cached_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dependency_id) REFERENCES dependencies(id)
);

-- Tasks (linear pipeline steps; executed in sequence_order within a project - no DAG/dependency graph yet, see Decision 5)
CREATE TABLE tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    task_type ENUM('python', 'sql', 'bash', 'ml_model') DEFAULT 'python',
    script_path VARCHAR(512),  -- Path to script within project
    sequence_order INT NOT NULL DEFAULT 0,  -- Execution order within the project's linear pipeline
    schedule_cron VARCHAR(100),  -- e.g., '0 * * * *' for hourly
    is_active BOOLEAN DEFAULT TRUE,
    last_run DATETIME,
    next_run DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

-- Task Runs
CREATE TABLE task_runs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id INT NOT NULL,
    status ENUM('pending', 'running', 'success', 'failed', 'skipped') DEFAULT 'pending',
    start_time DATETIME,
    end_time DATETIME,
    duration_seconds INT,
    triggered_by ENUM('scheduler', 'manual', 'api', 'upstream') DEFAULT 'manual',
    triggered_by_user_id INT,
    log_file_path VARCHAR(512),
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (triggered_by_user_id) REFERENCES users(id)
);

-- Execution Environments
CREATE TABLE execution_environments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_run_id INT,
    container_id VARCHAR(255),  -- Docker container ID
    image_name VARCHAR(255),
    status ENUM('creating', 'ready', 'running', 'stopped', 'failed') DEFAULT 'creating',
    resource_cpu INT,  -- in millicores
    resource_memory INT,  -- in MB
    network_mode ENUM('default', 'none', 'host', 'bridge') DEFAULT 'default',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_run_id) REFERENCES task_runs(id)
);
```

### ML Model Tables

```sql
-- ML Models
CREATE TABLE ml_models (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    model_type VARCHAR(100),  -- 'classification', 'regression', etc.
    current_version_id INT,
    storage_path VARCHAR(512),  -- Path to model artifacts
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (current_version_id) REFERENCES ml_model_versions(id)
);

-- ML Model Versions
CREATE TABLE ml_model_versions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    model_id INT NOT NULL,
    version VARCHAR(50) NOT NULL,
    framework VARCHAR(50),  -- 'pytorch', 'tensorflow', 'sklearn', etc.
    framework_version VARCHAR(50),
    metadata JSON,  -- Training params, performance metrics, etc.
    artifact_path VARCHAR(512),
    artifact_size INT,
    artifact_hash VARCHAR(64),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (model_id) REFERENCES ml_models(id)
);

-- ML Model Executions
CREATE TABLE ml_model_executions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    model_version_id INT NOT NULL,
    task_run_id INT,
    input_data JSON NOT NULL,
    output_data JSON,
    status ENUM('pending', 'running', 'success', 'failed') DEFAULT 'pending',
    start_time DATETIME,
    end_time DATETIME,
    duration_seconds INT,
    error_message TEXT,
    FOREIGN KEY (model_version_id) REFERENCES ml_model_versions(id),
    FOREIGN KEY (task_run_id) REFERENCES task_runs(id)
);
```

### Deployment & Approval Tables

```sql
-- Deployments
CREATE TABLE deployments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_version_id INT NOT NULL,
    environment_id INT NOT NULL,
    status ENUM('pending', 'approved_qa', 'rejected_qa', 'approved_prod', 'rejected_prod', 'deployed', 'failed', 'rolled_back') DEFAULT 'pending',
    requested_by INT NOT NULL,
    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    deployed_at DATETIME,
    rollback_reason TEXT,
    FOREIGN KEY (project_version_id) REFERENCES project_versions(id),
    FOREIGN KEY (environment_id) REFERENCES environments(id),
    FOREIGN KEY (requested_by) REFERENCES users(id)
);

-- Approvals
CREATE TABLE approvals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    deployment_id INT NOT NULL,
    approver_id INT NOT NULL,
    approval_type ENUM('qa', 'prod') NOT NULL,
    status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending',
    comments TEXT,
    approved_at DATETIME,
    FOREIGN KEY (deployment_id) REFERENCES deployments(id),
    FOREIGN KEY (approver_id) REFERENCES users(id)
);
```

### Monitoring Tables

```sql
-- Audit Logs
CREATE TABLE audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    action VARCHAR(100) NOT NULL,  -- 'create', 'read', 'update', 'delete', 'execute'
    resource_type VARCHAR(50) NOT NULL,  -- 'user', 'group', 'project', 'task', etc.
    resource_id INT,
    resource_name VARCHAR(255),
    details JSON,  -- Additional context
    ip_address VARCHAR(45),
    user_agent VARCHAR(255),
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Deployment Logs
CREATE TABLE deployment_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    deployment_id INT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    level ENUM('debug', 'info', 'warning', 'error', 'critical') DEFAULT 'info',
    message TEXT NOT NULL,
    context JSON,  -- Additional structured data
    FOREIGN KEY (deployment_id) REFERENCES deployments(id)
);

-- Security Logs
CREATE TABLE security_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    parse_result_id INT,
    task_run_id INT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    level ENUM('debug', 'info', 'warning', 'error', 'critical') DEFAULT 'info',
    event_type VARCHAR(50) NOT NULL,  -- 'scan_started', 'finding_detected', etc.
    message TEXT NOT NULL,
    details JSON,
    FOREIGN KEY (parse_result_id) REFERENCES security_parse_results(id),
    FOREIGN KEY (task_run_id) REFERENCES task_runs(id)
);

-- Execution Logs
CREATE TABLE execution_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_run_id INT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    level ENUM('debug', 'info', 'warning', 'error', 'critical') DEFAULT 'info',
    message TEXT NOT NULL,
    stdout TEXT,
    stderr TEXT,
    FOREIGN KEY (task_run_id) REFERENCES task_runs(id)
);

-- System Metrics
CREATE TABLE system_metrics (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    metric_type VARCHAR(50) NOT NULL,  -- 'cpu_usage', 'memory_usage', 'disk_usage'
    metric_value FLOAT NOT NULL,
    host VARCHAR(255),
    additional_data JSON
);

-- Alerts
CREATE TABLE alerts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    alert_rule_id INT NOT NULL,
    severity ENUM('low', 'medium', 'high', 'critical') DEFAULT 'medium',
    status ENUM('open', 'acknowledged', 'resolved') DEFAULT 'open',
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    triggered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME,
    resolved_by INT,
    FOREIGN KEY (alert_rule_id) REFERENCES alert_rules(id),
    FOREIGN KEY (resolved_by) REFERENCES users(id)
);

-- Alert Rules
CREATE TABLE alert_rules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    condition_type VARCHAR(50) NOT NULL,  -- 'threshold', 'anomaly', 'absence'
    condition_config JSON NOT NULL,  -- Configuration for the condition
    notification_channels JSON NOT NULL,  -- ['email', 'slack', 'webhook']
    notification_targets JSON,  -- Email addresses, Slack channels, etc.
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Security vulnerabilities in uploaded projects | High | Docker sandboxed execution (primary control) + blocking dependency-vulnerability scan once wired up; AST/bandit findings are audit-only, review those logs periodically |
| Database connection string security | High | Connection strings are encrypted at rest (`utils/security.py`); never log them; enforce clearance checks once the governance API exists |
| Docker execution in production | Medium | Resource limits are already parameterized in `utils/docker.py`; revisit Kubernetes only if scale requires it |
| Performance with many concurrent tasks | Medium | `ThreadPoolExecutor` worker count is configurable (`SCHEDULER_MAX_WORKERS`); revisit APScheduler-vs-Celery (Decision 2) if this becomes a bottleneck |
| Dependency caching size growth | Low | Not built yet - set size limits and a cleanup policy when it is |

---

## Success Criteria

### MVP
- [ ] Governance API/UI usable, not just the data models
- [x] Project upload working
- [ ] A task can actually be executed (scheduler wired to a trigger)
- [x] API layer with authentication
- [ ] Web UI reachable from a browser (login/session bridge closed - Decision 3)

### Full Feature Set
- [ ] All layers implemented, not just modeled
- [ ] Approval workflow working
- [ ] ML model execution functional
- [ ] Comprehensive monitoring and alerting
- [ ] Web UI covers tasks, deployments, and logs, not just projects/dashboard
- [ ] Automated test suite

---

*Plan created: 2026-09-08*
*Last updated: 2026-09-19*
