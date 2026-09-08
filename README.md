# Essential Pipeline - Data Pipeline & ML Platform

A project-oriented platform for building, testing, securing, deploying, and operating data pipelines and machine learning workloads.

The platform is designed as an alternative to assembling multiple tools such as Airflow, Docker, CI/CD, notebook environments, and ML model serving infrastructure.

Its primary goal is to make **data pipeline and ML workload development reproducible, isolated, secure, and governed**—particularly for organizations whose existing data environments are fragmented or lack a mature data architecture.

## Why

Many organizations have data, but not necessarily a well-structured data platform or medallion architecture.

Data may be distributed across:

- Multiple databases
- Legacy systems
- Excel/CSV files
- APIs
- Operational applications
- Data warehouses
- Ad-hoc datasets

Building useful data products in such environments often requires putting together:

- Airflow for orchestration
- Git and CI/CD for deployment
- Docker for isolation
- Notebook environments for development
- Dependency management for Python
- Security scanning
- Data governance
- ML model registries
- Model serving infrastructure

This project aims to provide these capabilities through a **single project-oriented execution platform**.

---

## Core Concepts

### Project

A project is the fundamental isolation and deployment unit.

A project contains the code, pipelines, dependencies, runtime environment, notebooks, configurations, and ML workloads required for a particular data or ML solution.

```text
Project
├── Pipelines
├── Tasks
├── Notebooks
├── Dependencies
├── Runtime Environment
├── Connections
├── ML Models
└── Configuration
```

Projects are independently versioned and executed.

### Pipeline

A pipeline defines a sequence of data processing or ML operations and their dependencies.

```text
Source
   v
Extract
   v
Transform
   v
Validate
   v
Feature Engineering
   v
Train Model
   v
Publish Model
```

Pipelines can contain different types of tasks, including Python, SQL, data processing, ML, and other execution types.

### Task

A task is an executable unit within a pipeline.

Tasks execute inside the project's isolated runtime environment and can use only the resources and connections permitted by project governance.

### Run

Every pipeline execution produces a traceable run containing execution status, logs, outputs, metadata, and artifacts.

---

# Development & Publishing

Unlike traditional Airflow deployments where DAG source files are commonly delivered to a shared `dags` directory through an external CI/CD process, this platform treats the **project itself as a versioned deployable artifact**.

A project can be packaged and uploaded as a ZIP:

```text
my-project-1.2.0.zip
```

The package may contain:

```text
project.yaml
pipelines/
notebooks/
src/
tests/
requirements.txt
Dockerfile
```

The platform validates and scans the project before publishing it.

## Project Lifecycle

```text
Develop
   v
Test
   v
Validate
   v
Security Scan
   v
Governance Gate
   v
Publish Version
   v
Deploy
   v
Run
```

Published versions are immutable and can be reproduced or rolled back.

---

# Notebook-Based Development

The platform is intended to support notebook-based development and testing.

Instead of requiring developers to build and deploy an entire pipeline before testing their code, development can happen progressively:

```text
Notebook
   v
Task
   v
Pipeline
   v
Project
   v
Published Version
```

This allows individual transformations, queries, feature engineering logic, and ML code to be tested before being incorporated into a production pipeline.

The goal is to make the development experience closer to how data scientists and engineers actually work while retaining production-grade execution.

---

# Isolated Execution

User code should not execute directly inside the platform's core Python environment.

Each project has its own runtime environment, implemented using containerized execution.

```text
Platform
│
├── Project A
│   └── Container
│       ├── Python
│       ├── Dependencies
│       └── User Code
│
├── Project B
│   └── Container
│       ├── Python
│       ├── Dependencies
│       └── User Code
│
└── Project C
    └── Container
        ├── Python
        ├── Dependencies
        └── User Code
```

This provides:

- Project isolation
- Dependency isolation
- Protection of the platform environment
- Reproducible execution
- Independent library versions
- Safer execution of user code

The **project version and its runtime environment should be treated as a single reproducible unit**.

For example:

```text
Project v1.4.2
+
Container Image SHA
+
Pipeline Definition
```

This allows a historical pipeline or ML model to be reproduced using the same execution environment.

---

# Dependency Management

A project owns its execution dependencies rather than sharing a large global Python environment.

Different projects can therefore use different versions of:

```text
pandas
numpy
scikit-learn
xgboost
PyTorch
TensorFlow
```

without creating conflicts in the platform runtime.

The platform is responsible for managing the execution infrastructure, while the project defines the libraries required by its workloads.

---

# Security Scanning

Publishing a project is a security boundary.

Before a project version can be published, the platform performs automated security and policy checks.

Potential scanning layers include:

### Source Code Analysis

AST/SAST-based analysis can identify potentially dangerous behavior such as:

- Arbitrary command execution
- `eval` / `exec`
- Suspicious imports
- Unsafe subprocess usage
- Unauthorized filesystem access
- Dynamic code loading
- Suspicious network access

### Dependency Scanning

Project dependencies can be checked for:

- Known vulnerabilities
- Suspicious packages
- Unpinned dependencies
- Dependency risks

### Secret Detection

The platform can detect accidentally committed:

- Passwords
- API keys
- Tokens
- Private keys
- Connection strings

### Container Scanning

The resulting project image can be scanned for known vulnerabilities in its operating system and installed packages.

Security scanning should be extensible so that specialized security tooling can be integrated over time.

---

# Governance

Security is not limited to scanning source code.

The platform also provides **governance gating** for project publishing and execution.

A project must satisfy applicable organizational policies before it can access protected resources or be deployed.

Examples include:

```text
Project
   v
Security Validation
   v
Governance Policy
   v
Approved?
   ├── No → Reject / Review
   └── Yes
         v
      Publish
```

Governance policies may control:

- Allowed connections
- Data classification
- Allowed environments
- Allowed libraries
- Allowed container images
- Network access
- Deployment permissions
- ML model deployment
- Production execution

---

# Cleared Connections

Connections are treated as governed resources rather than arbitrary credentials available to user code.

A project declares the connections it needs:

```yaml
connections:
  - customer_database
  - data_warehouse
  - external_api
```

The platform resolves these declarations against centrally managed and governed connections.

A connection can have properties such as:

```text
Connection
├── Owner
├── Classification
├── Allowed Projects
├── Allowed Environments
├── Allowed Operations
├── Credential Reference
└── Approval Status
```

User code should not need direct access to raw credentials.

This creates an important security boundary:

```text
User Code
   v
Declared Connection
   v
Governance Check
   v
Cleared Connection
   v
Resource
```

The objective is to prevent a pipeline from arbitrarily accessing databases, APIs, or other resources simply because the underlying runtime can technically reach them.

---

# Data Architecture

The platform does not assume that an organization already has a clean data architecture.

Instead, projects can progressively establish structured data flows over existing systems.

A typical project may evolve toward:

```text
Operational Sources
        v
      Raw
        v
     Cleaned
        v
   Transformed
        v
 Analytical Data
        v
 Feature Data
        v
      Models
```

This can provide a practical path toward medallion-style architecture without requiring the organization to redesign its entire existing data estate first.

---

# Machine Learning

ML workloads are first-class workloads within a project.

A project can contain:

```text
Data
 v
Feature Engineering
 v
Training
 v
Evaluation
 v
Model Version
 v
Deployment
 v
Inference
```

The platform is intended to support:

- Model training
- Model versioning
- Model artifacts
- Reproducible training environments
- Model deployment
- Model serving
- Batch inference
- Pipeline-triggered inference

A model should retain the relationship between:

```text
Model Version
    v
Project Version
    v
Runtime Environment
    v
Training Run
    v
Input Data / Features
```

This makes ML workloads reproducible and traceable.

---

# Architecture Direction

The initial architectural direction is:

```text
                    Platform
                       │
             ┌─────────┴─────────┐
             │                   │
         Projects             Governance
             │                   │
     ┌───────┼────────┐          │
     │       │        │          │
 Pipelines Tasks  Notebooks      │
     │       │        │          │
     └───────┼────────┘          │
             v                   │
       Project Runtime ←─────────┘
        (Container)
             │
     ┌───────┼──────────┐
     v       v          v
   Data    Artifacts   Models
 Sources
```

---

# Design Principles

The platform is being designed around several principles:

1. **Project over DAG**\
   The project is the primary unit of isolation, development, deployment, and governance.

2. **Version everything**\
   Code, pipelines, environments, models, and execution results should be traceable to versions.

3. **Isolate user code**\
   User workloads should not share the platform's execution environment.

4. **Environment follows the project**\
   Dependencies should be defined and reproduced with the workload.

5. **Security before publishing**\
   A project should pass security checks before becoming a deployable version.

6. **Govern access rather than trust code**\
   User code should access enterprise resources through cleared, governed connections.

7. **Develop progressively**\
   Developers should be able to test code at notebook, task, and pipeline levels before publishing.

8. **Support imperfect data estates**\
   The platform should work with existing messy data environments rather than requiring a mature data platform as a prerequisite.

9. **Data and ML are first-class workloads**\
   The platform is more than a scheduler; it manages the lifecycle of data processing and ML workloads.

---

# Project Status

**Early-stage / Experimental**

The architecture and implementation are evolving.

Initial areas of development:

- [ ] Project management and isolation
- [ ] Versioned project ZIP packaging
- [ ] Pipeline definition and execution
- [ ] Containerized task execution
- [ ] Dependency/environment management
- [ ] Notebook-based development
- [ ] Project validation
- [ ] Security scanning
- [ ] Governance gates
- [ ] Cleared connections
- [ ] Pipeline scheduling
- [ ] Execution monitoring
- [ ] ML model training
- [ ] Model registry
- [ ] Model hosting / serving
- [ ] Data lineage and artifacts

---

## Vision

The long-term goal is to provide a **self-contained, project-oriented platform for data engineering and machine learning** where a team can move from exploratory code to a governed production workload without assembling and maintaining a large collection of separate infrastructure components.

The platform should make this workflow possible:

```text
Explore
   v
Develop
   v
Test
   v
Package
   v
Scan
   v
Govern
   v
Publish
   v
Deploy
   v
Run
   v
Monitor
   v
Reproduce
```
