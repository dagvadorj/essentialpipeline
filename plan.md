# EssentialPipeline - Implementation Plan

## Status Summary

**Working end-to-end today, fully verified including real container execution**: user registration/login (JWT, both API bearer tokens and a browser login page/cookie session bridge - Decision 3), project CRUD with zip upload and versioning (API and web UI), the web dashboard, the Flask-Admin governance panel, and Alembic migrations validated against MySQL. All 32 data models across the governance/execution/monitoring/deployment layers are implemented. Task execution is wired end to end and confirmed against a real Docker daemon: create a task (API or web UI) → trigger it (`POST /api/v1/tasks/<id>/trigger`, `POST /user/tasks/<id>/trigger`, or a cron schedule registered at startup) → extract the project's uploaded zip → run it in a container → capture its output into an `ExecutionLog` → mark the `TaskRun` `success`. Verified with the `hello_pipeline` example project's real stdout coming back through the whole path.

Getting a real Docker daemon in the loop (the user started Docker Desktop) surfaced four bugs in `utils/docker.py`/`services/scheduler.py` that the earlier "Docker unavailable" testing couldn't reach, all now fixed:
- `docker==7.0.0` doesn't work with `requests>=2.32` (raises `Not supported URL scheme http+docker` regardless of whether a daemon is running) - bumped to `docker==7.1.0` in `requirements.txt`.
- `containers.create()` doesn't auto-pull a missing image the way `docker run` does - added `DockerContainer._ensure_image()`.
- The container was created with no process of its own, so `python:3.11-slim`'s default CMD (the `python3` REPL) hit EOF on its unattached stdin and exited almost immediately, tearing the container down mid-`exec_run` (exit code 137, always, on any machine). Fixed by giving the container a `sleep infinity` keep-alive process to exec into.
- `Container.exec_run()` has no `timeout` parameter in docker-py at all - passing one was a guaranteed `TypeError` the first time this code path ever ran anywhere. Replaced with a worker-thread-plus-`join(timeout)` pattern that force-stops the container if a task overruns, since an unbounded hang would otherwise permanently occupy one of a fixed-size `ThreadPoolExecutor`.
- `execute_task_in_container`'s result dict never had a `'logs'` key, so `execute_task`'s `if result.get('logs')` check for saving an `ExecutionLog` was always false - no run's output was ever being captured. Fixed by mirroring `result['output']` (exec_run's merged stdout+stderr) into `result['logs']`.

**Not started**: Garage integration (project files currently live on local disk only), ML model execution, monitoring/alerting, rate limiting, API documentation, and CI. (This line used to also list security scanning, the deployment/approval workflow, and "no git repository" - all stale: security scanning and the deployment/approval workflow were both wired up in later passes, see Governance and Scheduling & Deployment below, and this has been a real git repo with a GitHub remote since early in the project's history - the Foundation checklist below had simply never been updated to reflect any of it.)

**One open contradiction between a recorded decision and the actual code**, to resolve before building further on it:
- **Storage** (Decision 4): committed to Garage; `utils/storage.py` only writes to local disk, and `services/scheduler.py` has a comment acknowledging the Garage copy step is skipped.

(Task orchestration, formerly the other open contradiction, is resolved - see Decision 5.)

**Described in `README.md` but not yet implemented**: notebook-based progressive development (Decision 8: one project = one pipeline = one notebook - decided, but the notebook side has zero implementation and is missing from the Web UI layer), secret detection and container-image scanning (Decision 6 - decided, but neither has a library chosen or a service written), the project manifest/package format (`project.yaml`), medallion-style data architecture guidance, and the model-lineage traceability chain.

Checkboxes in this document track real implementation status, not aspiration - update them as work lands.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                Web UI Layer (Flask + Jinja2, server-rendered)         │
├─────────────────────────────────────────────────────────────────────┤
│  User Dashboard    Project CRUD/Upload    Task/Deployment/Log Views   │
│  Notebook Editor (one per project, not yet implemented - Decision 8)  │
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
Status: container lifecycle implemented in `utils/docker.py` (create/start/stop/execute/logs/cleanup), triggered by both `POST /api/v1/tasks/<id>/trigger` and `POST /user/tasks/<id>/trigger`, and verified end to end against a real Docker daemon (see Status Summary for the bugs that surfaced and were fixed along the way).

### 2. Scheduler: APScheduler, not Celery/Redis
Implemented with APScheduler + a `ThreadPoolExecutor` instead of Celery/Redis - one less moving piece (no message broker) at the current scale. Revisit if concurrency needs outgrow a single process.
Status: implemented in `services/scheduler.py`; `schedule_all_tasks()` is now called at startup (`app/__init__.py`, after `db.create_all()`) so cron-scheduled tasks register with APScheduler, and manual/API triggers go through the `ThreadPoolExecutor` via `queue_task_execution()`. Both paths push a Flask app context (`_execute_task_entrypoint`) before touching `db.session`, since neither APScheduler's background thread nor the executor's worker threads have a Flask request context of their own.

### 3. Auth: JWT (Flask-JWT-Extended)
Stateless, standard fit for a REST API.
Status: implemented for both API and web UI. `/login` (`app/routes/user/auth.py`) authenticates and sets the access/refresh JWTs as httponly cookies (`JWT_TOKEN_LOCATION = ['headers', 'cookies']`); API callers keep using the bearer header, browser navigations to `/user/*` or `/admin/*` with a missing/invalid/expired token now redirect to `/login?next=...` instead of returning raw JSON 401 (`unauthorized_loader`/`invalid_token_loader`/`expired_token_loader` in `app/__init__.py`). CSRF protection is intentionally left off the JWT cookie (`JWT_COOKIE_CSRF_PROTECT = False`) since no form elsewhere in the app has CSRF tokens either - revisit together.

### 4. Storage: Garage for files, MySQL for metadata
Keeps large binary files (project archives, model artifacts, logs) out of the relational database.
Status: not implemented. `utils/storage.py` writes only to local disk under `UPLOAD_FOLDER`. Needs either real Garage client work or a decision to stay on local disk for now.

### 5. Task orchestration: dependency graph via `TaskDependency` (revised from linear pipeline)
Originally decided as sequential execution (`Task.sequence_order`, deferring a dependency graph "until there's a proven need for it"). Revisited: `services/scheduler.py` already implements the DAG-style dependency execution this was meant to defer - `execute_task` skips a task when any `TaskDependency` it declares hasn't had a successful run, and `trigger_dependent_tasks` cascades to dependents on success - and the `TaskDependency` model is already part of the shipped schema. Ripping that out to replace it with a `sequence_order` column that doesn't exist yet would throw away working code to reach a simpler design with no functional need driving the simplification. `Task.sequence_order` is dropped from the plan; task order within a project is expressed entirely through `TaskDependency` edges.
No cycle detection exists yet (`execute_task`/`trigger_dependent_tasks` walk `TaskDependency` without checking for cycles) - a cyclic dependency would currently deadlock a task into permanently "skipped" rather than erroring. Needs a cycle check (e.g. at task-dependency creation time) before this is exposed to users.
Status: decided. Scheduler logic already matches this decision; no scheduler changes needed for this specific item. Remaining gap is the cycle-detection check above, plus wiring described in the Status Summary (nothing calls `schedule_all_tasks()` or triggers a manual run yet).

### 6. Security scanning: README's four layers, split by whether isolation already covers the risk
Follows README's four scanning layers (source code, dependency, secret detection, container image), split into blocking vs. audit-only by the same rule: if Docker isolation already covers the risk, a blocking gate on top is mostly false-positive friction and stays audit-only; if the finding is a real, usable credential regardless of isolation, it blocks.
- **Source code (AST/SAST, Bandit)**: audit-only. Isolation covers what a malicious code pattern could do at runtime.
- **Dependency vulnerabilities (Safety)**: blocks. A running project is granted real DB/storage credentials, so a known-vulnerable package is a live risk independent of isolation.
- **Secret detection**: blocks. A credential accidentally committed into a project is a live, usable credential, same rationale as dependency scanning.
- **Container image scanning**: audit-only. Same isolation argument as source code - a vulnerable base-image package inside an already-isolated, per-project container is defense-in-depth, not a live credential exposure.
Status: decided (all four layers), but only two are implemented as dependencies: Safety and Bandit are listed in `requirements.txt` but neither is called from any service. Secret detection and container image scanning have no library chosen and no service written yet.

### 7. Web UI: server-rendered Flask + Jinja2, no htmx/SPA
Plain links/forms with full page reloads. No separate build pipeline or client-side framework; a genuinely-needed dynamic refresh later gets a small hand-written `fetch()` call instead of a library.
Status: dashboard, project pages, and the Flask-Admin panel work this way today. Real browser use is now unblocked by the Decision 3 login/session bridge.

### 8. Cardinality: one project = one pipeline = one notebook
A project does not contain multiple named pipelines or multiple notebooks. Each project has exactly one pipeline (its tasks and the `TaskDependency` edges between them, Decision 5) and exactly one notebook (its progressive-development surface, per README's `Notebook → Task → Pipeline → Project` flow). "Pipeline" is documentation language for "this project's task graph," not a separately nameable/orderable object - no `Pipeline` model is needed.
Status: decided. Pipeline side is implemented via `Task`/`TaskDependency`, scoped to a project through `Task.project_id` (Decision 5). Notebook side is not implemented at all: no model, no in-browser editor/kernel, no route, and it doesn't appear in the Web UI Layer of the Architecture Overview diagram above.

---

## Progress by Layer

### Governance
- [x] Models: `User`, `Group`, `Permission`, `Environment`, `DatabaseConnection`, `StorageConnection`, `GroupConnectionClearance`, `AuditLog`
- [x] Connection-string encryption (`utils/security.py`, Fernet)
- [x] Audit logging middleware (best-effort, non-blocking)
- [x] Governance API/UI: groups (create, detail, permission assignment), connection clearances (grant/update/revoke, with the polymorphic `connection_type`/`connection_id` resolved to a real connection name - the one thing Flask-Admin's auto-generated forms couldn't do), and connection testing, both as a web UI (`app/routes/admin/governance.py`, gated by the previously-unused `admin_required` decorator) and an equivalent API (`app/routes/api/v1/admin.py`, `/api/v1/admin/...`). Permissions/Environments/raw connection CRUD deliberately left to Flask-Admin rather than duplicated, since it already handles those tables well - the governance UI links out to it for that. Verified end to end via the real HTTP test client, including a non-admin 403 and a real (correctly-failing) live connection test.
- [x] Connection health-check endpoint / connection testing utility (`services/connection_health.py`) - always confirms the stored credential decrypts; attempts a real live connect for `mysql` connections (the only DB driver installed) and reports "decrypt-only, can't live-test" for connection types/storage with no driver installed, rather than silently pretending to have tested them
- [x] Environment promotion state machine (`services/deployment.py`) - `Deployment`/`Approval` were pure data models with nothing creating or transitioning them; now `pending -> approved_qa -> [approved_prod ->] deployed -> rolled_back` (or `rejected_qa`/`rejected_prod`), gated by the seeded `deployment_request`/`deployment_approve`/`deployment_manage` `Permission`s the same way the Governance Gate reuses `project_write` - fails closed by default. A non-production `Environment` only needs the one qa-type approval; production needs a second, separate prod approval - see Scheduling & Deployment for the full writeup and web UI/API routes.
- [x] Audit log query API - both `GET /admin/governance/audit-logs` (web UI, paginated, filterable by action/resource_type/user_id) and `GET /api/v1/admin/audit-logs` (same filters, JSON, paginated)
- [x] Governance Gate as an explicit pre-publish check (`services/governance_gate.py`). Added a real publish step to the lifecycle - `ProjectVersion` gained `is_published`/`published_at`/`published_by` (migration `34f7f3593b96`) - since none existed before; a version is created unpublished, and `POST /user/projects/<id>/versions/<id>/publish` / `POST /api/v1/projects/<id>/versions/<id>/publish` gate it on two checks: (1) no blocking `SecurityParseResult` and (2) the publishing user belongs to a group holding a `project` `write`/`admin` `Permission` - fails closed if no such grant exists, rather than letting everyone through by default. Check (1) now has real data behind it too (see Security scanning below) - confirmed end to end that a project with an actual vulnerable dependency gets blocked while one with only an audit-only finding doesn't, matching Decision 6's split exactly. Also verified: blocked with no clearance, allowed after granting it, rejects re-publishing, rejects a version/project mismatch.
- [ ] Secret detection scanning (Decision 6)
- [ ] Container image scanning (Decision 6)

### Execution
- [x] Models: `Project`, `ProjectVersion`, `ProjectFile`, `SecurityParseResult`, `SecurityFinding`, `Dependency`, `DependencyCache`, `ExecutionEnvironment`
- [x] Project CRUD + zip upload + versioning, both API and web UI
- [x] Docker container lifecycle (`utils/docker.py`) - triggered on every task run (see Decision 1) and verified against a real daemon, including a task's actual stdout coming back through `ExecutionLog`
- [ ] File storage on Garage (currently local disk - Decision 4)
- [x] Uploaded zip is validated at upload time (`utils/project_validation.py`, wired into all 4 upload paths - `user/projects.py`'s `new_project`/`upload_project_version` and `api/v1/projects.py`'s create/upload) - rejects a corrupt/non-zip file, zip-slip paths, absolute paths, and archives over a 500MB uncompressed / 5000-entry cap. Deliberately metadata-only (reads the zip's central directory, never decompresses) so validating an untrusted upload can't itself become a zip-bomb resource-exhaustion vector on the app server. Verified against 8 cases including a real ~1000x zip bomb (500KB compressed / 500MB+ declared uncompressed), caught from metadata alone.
- [x] Project manifest format - a minimal `project.yaml` schema (`name`, and `tasks: [{name, type, script, schedule}]`), documented and validated in `utils/project_validation.py`. Deliberately optional (a zip with no `project.yaml` still works exactly as before) and forward-compatible (unrecognized keys are ignored, not rejected) - rejects a task with an unknown `type`, a `script` that doesn't exist in the zip, or an invalid cron `schedule` (parsed via APScheduler's own `CronTrigger`, not reimplemented). Verified against 11 cases. Doesn't (yet) auto-create `Task` rows from the manifest - "validated" was the scope here, not "acted on"; `pipeline.yaml`/`notebook/`/`Dockerfile` from README's fuller sketch remain undefined, since nothing in the app consumes them today. `essentialpipeline/examples/hello_pipeline/project.yaml` added as a real example.
- [x] Downloadable example/template project zip - `essentialpipeline/examples/hello_pipeline/`, served zipped-on-the-fly at `GET /user/projects/example` and linked from the new-project and upload-version forms. Beyond the single `main.py` smoke-test script, it now has a small 3-task ETL pipeline (`extract.py` → `transform.py` → `load.py`, sharing a `pipeline_data.py` helper module) over synthetic order data, so the example demonstrates a project with several real tasks rather than just one, plus a `project.yaml` manifest listing them. Each step falls back to regenerating its input deterministically if the previous step's output file isn't present, since task runs don't share a persistent volume with each other yet (Decision 4) - documented in the example's own `README.md`. All three tasks verified running successfully end to end against a real Docker daemon.
- [ ] Dependency extraction/caching from a project's `requirements.txt`
- [x] Security scanning wired up (Decision 6, partially) - `services/security_scan.py` runs Bandit (source/AST, audit-only - findings recorded but never block) and Safety (dependency vulnerabilities against `requirements.txt` if present - any finding blocks) right after every upload, creating real `SecurityParseResult`/`SecurityFinding` rows the Governance Gate's security-scan check now actually has data to evaluate. Best-effort throughout: a scanner tool failing to run never blocks the upload that triggered it. Verified against real vulnerable code (`subprocess(shell=True)`, flagged by Bandit but correctly non-blocking on its own) and a real vulnerable dependency (`django==2.0.1`, ~64 known CVEs via Safety, correctly blocking) - confirmed the Governance Gate now actually discriminates between them exactly per Decision 6's split. Secret detection and container image scanning (the other two Decision 6 layers) still have no library chosen and aren't run.
- [ ] Medallion-style data architecture guidance (README: raw → cleaned → transformed → analytical → feature) - conceptual only; no tooling, template project, or convention enforces this progression today

### Development Experience
- [ ] Notebook-based development (README's `Notebook → Task → Pipeline → Project → Published Version` progressive workflow; Decision 8: one project = one pipeline = one notebook) - no notebook model, no in-browser notebook editor/kernel, no execution path; a task currently can only be authored as a file inside an uploaded project, not iterated on in-platform. Not present anywhere in the Web UI layer.

### Web UI
- [x] Base layout + navigation
- [x] Dashboard (stats computed on page load; the `/user/stats` JSON endpoint exists but is currently unused)
- [x] Project pages: list, create, detail, edit, upload, delete
- [x] Admin panel via Flask-Admin: Users, Groups, Permissions, Environments, DB/Storage Connections, Audit Logs, Projects, Tasks, ML Models
- [x] Task pages: list, create, detail with run history, manual trigger (`templates/user/tasks/`); also surfaced on the project detail page
- [x] Deployment pages: list (own projects' deployments, plus every deployment for anyone holding `deployment_approve`/`deployment_manage` - an approver needs to see requests outside their own projects to review them), request (`templates/user/deployments/`), detail with approve/reject/deploy/rollback actions gated on status + permission, and approval history; wires the two dead links this page's nav already had ("My Deployments"/"Request Deployment") plus project detail's dead "Deploy" quick action
- [x] Log viewer pages (`templates/user/logs/`) - a single page with a type selector across the three log tables that actually get written (execution/deployment/security), filterable by level; wires the previously-dead "Logs" nav link. ML model pages too (`templates/user/models/`) - record CRUD only (list/create/detail/edit/delete), not versions/artifacts/execution, which is a separate, larger piece of work; wires "My Models"/removes the "Test Model" link, since testing implies execution that doesn't exist yet
- [ ] Notebook editor page (Decision 8) - not started; a project's one notebook has no browser surface at all today
- [x] Login page / session bridge (Decision 3)

### Scheduling & Deployment
- [x] Models: `Task`, `TaskRun`, `TaskDependency`, `MLModel`, `MLModelVersion`, `MLModelExecution`, `Deployment`, `Approval`
- [x] Scheduler service written (`services/scheduler.py`) - implements the DAG dependency logic Decision 5 now commits to; wired in (see below)
- [x] Cycle detection on `TaskDependency` (Decision 5) - `services/task_dependencies.py`'s `creates_cycle()`, wired into Flask-Admin's `TaskDependencyModelView.on_model_change` (the only place a `TaskDependency` can be created, since it isn't exposed anywhere else yet); also rejects edges crossing project boundaries. Verified via the real Flask-Admin form: a cyclic edge and a cross-project edge are both rejected without creating a row, a legitimate edge still gets created. Surfaced and fixed a real SQLAlchemy autoflush bug along the way - querying inside `on_model_change` was flushing the not-yet-ready pending row and crashing; fixed with `db.session.no_autoflush`.
- [x] `schedule_all_tasks()` called at startup (`app/__init__.py`, after `db.create_all()`) so cron-scheduled tasks get registered with APScheduler
- [x] A task can actually be triggered from the API (`POST /api/v1/tasks/<id>/trigger`, `GET /api/v1/tasks/<id>/runs`) and the web UI (`user/tasks.py` list/new/detail/trigger pages, plus a Tasks section on the project detail page); verified end to end through the real HTTP test client - task creation, trigger, zip extraction, and TaskRun status transitions (`pending` → `running` → `failed`, since Docker itself isn't available in this dev environment) all confirmed working
- [x] Uploaded project zip is extracted at execution time (`extract_project_archive()` in `services/scheduler.py`) so a triggered task has real code to run; guards against zip-slip since this runs on the host before the container's isolation exists
- [ ] ML model artifact upload/download, model execution service
- [x] Environment promotion workflow / approval state machine / rollback - `services/deployment.py` (see Governance for the full writeup); `POST /user/deployments/<id>/{approve,reject,deploy,rollback}` and the API equivalents under `/api/v1/deployments/...`. `mark_deployed()` is deliberately state + timestamp bookkeeping only, not a real deployment mechanism - there's nowhere for a "deployed" project to actually run beyond the existing Docker task execution, since Decision 4/Garage (the storage layer a real deploy would need) isn't built. Verified end to end against the real MySQL dev DB: the full `pending → approved_qa → approved_prod → deployed → rolled_back` path for a production environment, a non-production environment correctly skipping the prod approval stage, self-approval correctly rejected, and 20 automated tests (`tests/test_deployment.py`) covering the state machine and both route surfaces.
- [ ] Model lineage chain surfaced/queryable (README: `Model Version → Project Version → Runtime Environment → Training Run → Input Data/Features`) - the individual FK fields exist across `MLModelVersion`/`MLModelExecution`/`ProjectVersion`/`ExecutionEnvironment`, but nothing joins or exposes the full chain

### Monitoring
- [x] Models: `DeploymentLog`, `SecurityLog`, `ExecutionLog`, `SystemMetric`, `Alert`, `AlertRule`
- [x] Health check endpoints (`/health`, `/api/v1/health`)
- [ ] Structured/centralized logging service (currently ad hoc `logging` calls)
- [x] Log querying (`GET /api/v1/logs/{execution,deployment,security}`, paginated, filterable by level/source id) - not aggregation/export, which are separate, larger pieces of work (a real log-aggregation pipeline, and export tooling). Building this surfaced that `DeploymentLog` and `SecurityLog` were, like `Deployment`/`Approval` before the approval workflow, pure never-written data models - only `ExecutionLog` was actually populated. Now wired into `services/deployment.py` (one entry per state transition) and `services/security_scan.py` (scan_started/finding_detected per finding/scan_completed)
- [ ] System metrics collection (model exists, nothing populates it)
- [ ] Alerting (email/Slack)

### API Layer
- [x] JWT authentication (register/login/refresh/logout/me/list-users/password change)
- [x] Project endpoints (CRUD, upload, versions, task creation)
- [x] Task/model/deployment/log endpoints - task (earlier pass), deployment (`services/deployment.py`), and log (`GET /api/v1/logs/...`) endpoints are real; ML model endpoints are record CRUD only (`api/v1/models.py`) - versions/artifacts/execution remain a separate, larger piece of work
- [x] RBAC applied to routes - `admin_required` is used (all of `admin/governance.py` and `api/v1/admin.py`, see Governance); `project_access_required` now wired into all 8 project-scoped routes in `api/v1/projects.py` (get/update/delete/upload/versions/tasks), enhanced to stash the fetched project on `g.project` so views don't re-query. Doing this surfaced a real bug: `abort(403)` from an API route was returning Flask's default HTML error page instead of JSON (no 403 handler existed, unlike 404/500) - fixed with a `forbidden_handler` mirroring the existing pattern, which also fixed `admin_required`'s API responses. Web UI project routes (`user/projects.py`) deliberately keep their own inline flash+redirect checks rather than adopting this decorator, since `abort(403)` is a worse UX there than a friendly redirect.
- [ ] Rate limiting
- [ ] Request/response schema validation
- [ ] OpenAPI/Swagger documentation

### Foundation
- [x] Flask/SQLAlchemy application factory, dependency set fixed and installable in a clean venv
- [x] Alembic initialized; initial migration generated and validated against MySQL
- [x] `.env`/config wired to real values (DB host, JWT/encryption secrets)
- [x] Git repository initialized - this was stale; a real repo with a GitHub remote (`origin`) has existed since early in the project's history, this checkbox had just never been updated

### Testing & Deployment
- [x] Automated tests - `tests/` (pytest), covering the highest-risk/most-recently-fixed areas: task execution (mocked Docker, plus a small real-Docker-daemon suite auto-skipped when none is reachable), cycle detection, the Governance Gate, security scanning, zip/manifest validation, `admin_required`/`project_access_required`, and upload/task routes end to end. 124 tests, self-contained (in-memory SQLite, no external DB needed) and passing reliably (verified stable across repeated full-suite runs). `tests/README.md` covers how to run it and a real bug found while writing it: `get_config()` ignores `create_app()`'s `config_env` argument and reads `FLASK_ENV` from the OS environment instead - worked around at the test-harness level (`conftest.py` sets `FLASK_ENV=testing`), not yet fixed at the source.
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
- **Scanning**: Safety 2.3.5 (dependency, blocking) and Bandit 1.7.7 (source/AST, audit-only) are in `requirements.txt` but not wired up yet; secret detection and container image scanning (Decision 6) are decided but no library is chosen and neither is in `requirements.txt` yet

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
    overall_status ENUM('passed', 'warning', 'failed') DEFAULT 'passed',  -- 'warning' = AST/bandit or container image findings (non-blocking), 'failed' = vulnerable dependency or detected secret (blocks execution) - see Decision 6
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

-- Tasks (a project's pipeline steps; order and fan-out come from task_dependencies below, not a sequence column - see Decision 5)
CREATE TABLE tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    task_type ENUM('python', 'sql', 'bash', 'ml_model') DEFAULT 'python',
    script_path VARCHAR(512),  -- Path to script within project
    schedule_cron VARCHAR(100),  -- e.g., '0 * * * *' for hourly
    is_active BOOLEAN DEFAULT TRUE,
    last_run DATETIME,
    next_run DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

-- Task Dependencies (DAG edges within a project's task graph - Decision 5; cycle detection enforced in app code, not a DB constraint - see services/task_dependencies.py)
CREATE TABLE task_dependencies (
    task_id INT NOT NULL,             -- the task that has a dependency
    depends_on_task_id INT NOT NULL,  -- the task it depends on
    PRIMARY KEY (task_id, depends_on_task_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (depends_on_task_id) REFERENCES tasks(id)
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
| Security vulnerabilities in uploaded projects | High | Docker sandboxed execution (primary control) + blocking dependency-vulnerability and secret-detection scans once wired up; AST/bandit and container image findings are audit-only, review those logs periodically (Decision 6) |
| Database connection string security | High | Connection strings are encrypted at rest (`utils/security.py`); never log them; enforce clearance checks once the governance API exists |
| Docker execution in production | Medium | Resource limits are already parameterized in `utils/docker.py`; revisit Kubernetes only if scale requires it |
| Performance with many concurrent tasks | Medium | `ThreadPoolExecutor` worker count is configurable (`SCHEDULER_MAX_WORKERS`); revisit APScheduler-vs-Celery (Decision 2) if this becomes a bottleneck |
| Dependency caching size growth | Low | Not built yet - set size limits and a cleanup policy when it is |

---

## Success Criteria

### MVP
- [x] Governance API/UI usable, not just the data models (groups, clearances, connection testing, and audit log queries - web UI and API, verified end to end)
- [x] Project upload working
- [x] A task can actually be executed (scheduler wired to a trigger, verified against a real Docker daemon end to end)
- [x] API layer with authentication
- [x] Web UI reachable from a browser (login/session bridge closed - Decision 3)

**All four MVP criteria are now met.**

### Full Feature Set
- [ ] All layers implemented, not just modeled
- [x] Approval workflow working - see Scheduling & Deployment / `services/deployment.py`
- [ ] ML model execution functional
- [ ] Comprehensive monitoring and alerting
- [x] Web UI covers tasks, deployments, and logs, not just projects/dashboard - see Web UI
- [x] Automated test suite - `tests/` (pytest, 124 tests) - see Testing & Deployment
- [ ] Notebook-based progressive development, one per project, in the Web UI (Decision 8)
- [ ] Secret detection and container image scanning wired up (Decision 6) - Bandit + Safety are wired (see Governance); these two remaining layers still have no library chosen
- [x] Project manifest (`project.yaml`) defined and validated on upload - see Execution (this was already done and just stale here)

---

*Plan created: 2026-09-08*
*Last updated: 2026-09-20. All four MVP criteria are met, plus a full, verified path from upload through to a deployed-and-rollback-able release:

login (Decision 3) → upload (zip-safety + optional `project.yaml` manifest validation, `utils/project_validation.py`) → task execution (Decisions 1/2/5, real Docker daemon verified, `services/scheduler.py`) → security scan on upload (Bandit audit-only + Safety blocking, `services/security_scan.py`) → publish, gated by the Governance Gate (`services/governance_gate.py`) on clearance + scan results → deploy, gated by the environment promotion state machine (`services/deployment.py`) on `deployment_request`/`deployment_approve`/`deployment_manage` clearance, production environments needing a second separate approval stage → rollback. Plus the governance admin UI/API (`admin/governance.py`, `api/v1/admin.py`), RBAC (`admin_required`/`project_access_required`), a log viewer and ML model record CRUD closing out the last stub routes/pages (`api/v1/logs.py`, `api/v1/models.py`, `user/logs.py`, `user/models.py`), and an automated test suite (`tests/`, pytest, 141 tests, self-contained on in-memory SQLite - see Testing & Deployment) covering all of it.

Every item was verified against real inputs, not just unit-level checks - a real Docker daemon, a real vulnerable dependency (django==2.0.1, ~64 CVEs), a real zip bomb, a real cyclic dependency, the full deployment state machine against the real MySQL dev DB. See the Decisions and Progress-by-Layer sections for the specifics and the real bugs each pass found and fixed along the way (several - `docker-py`/`requests` incompatibility, missing image pull, no container keep-alive process, an `exec_run` kwarg that doesn't exist, a SQLAlchemy autoflush bug, API 403s returning HTML instead of JSON, `get_config()` ignoring `create_app()`'s config_env, a cross-test executor race, an ambiguous-join bug in the new log queries caught by the test suite itself before it ever shipped). Also found while building the log viewer: `DeploymentLog` and `SecurityLog` were, like `Deployment`/`Approval` before the approval workflow, pure never-written data models - now wired into `services/deployment.py` and `services/security_scan.py` respectively.

Known gaps: secret detection and container image scanning (Decision 6's other two layers) still have no library chosen; `pipeline.yaml`/`notebook/`/`Dockerfile` from README's fuller manifest sketch remain undefined since nothing consumes them; the `project.yaml` manifest doesn't yet auto-create `Task` rows, only validates; ML model versions/artifact upload/execution, log aggregation/export, and ongoing monitoring/alerting are still unbuilt (see Scheduling & Deployment / Monitoring).*
