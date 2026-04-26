"""
Sample PRD for unit tests.
Used by: EntityExtractor tests, PrdValidator tests, ConsistencyEngine tests.
Avoids LLM calls — deterministic, fast, cheap.
"""

VALID_PRD = """
# Product Requirements Document
## TaskFlow — Project Management for Remote Teams

**Version:** 1.0
**Status:** Draft

## 1. Product Overview

TaskFlow is a project management platform for remote software teams. It provides a structured
workspace where teams can organise work into Projects, track individual Tasks, and collaborate
through comments and file attachments.

## 2. Problem Statement

Remote teams lose visibility when work is scattered across email, chat, and spreadsheets.
Managers cannot see workload distribution without manual status updates. Engineers spend time
in status meetings instead of building.

## 3. Target Users

### Primary User
Engineering Manager — owns 1–3 Projects, needs workload visibility without micromanaging.

### Secondary User
Engineer — works on 3–8 Tasks at a time, wants clear priorities and due dates.

## 4. Key Features

### Feature: Task Management
**Description:** Engineers create, assign, and track Tasks within a Project.
**Acceptance Criteria:**
- [ ] An authenticated Member can create a Task via POST /tasks and receive HTTP 201 within 500ms
- [ ] A Task must have: title (required), status (open/in_progress/done), due_date (optional), assignee_member_id (optional)
- [ ] Task status changes are recorded in an AuditLog with timestamp and actor

### Feature: Workspace Management
**Description:** Organisation owners create a Workspace and invite Members.
**Acceptance Criteria:**
- [ ] A Workspace owner can invite a new Member via POST /workspaces/{id}/members using email address
- [ ] Invited Member receives an email with an accept link valid for 48 hours
- [ ] Maximum 50 Members per Workspace in the MVP

### Feature: Project Organisation
**Description:** Members create Projects inside a Workspace to group related Tasks.
**Acceptance Criteria:**
- [ ] An authenticated Member can create a Project via POST /projects within their Workspace
- [ ] A Project contains Tasks and has: name, description, status (active/archived), owner_member_id
- [ ] Archiving a Project does not delete its Tasks

### Feature: Manager Dashboard
**Description:** Managers see workload per Member and overdue Tasks across all Projects.
**Acceptance Criteria:**
- [ ] GET /workspaces/{id}/dashboard returns Member list with open Task count per Member
- [ ] Dashboard highlights Tasks with due_date in the past and status != done
- [ ] Dashboard data refreshes within 60 seconds of any Task status change

## 5. User Flows

### Flow: Create and assign a task
```
1. Member opens Project view
2. Member clicks "New Task"
3. Member sets title, due date, assignee
4. System creates Task via POST /tasks → HTTP 201
5. Assignee receives in-app notification
```

### Flow: Invitation rejected (expired link)
```
1. Owner sends invite to engineer@example.com
2. Engineer waits > 48 hours
3. Engineer clicks accept link
4. System returns HTTP 410 Gone: "Invitation expired"
5. Owner must re-send invite
```

## 6. Non-Functional Requirements

| Category | Requirement | Target |
|----------|-------------|--------|
| Performance | API response time | < 200ms at p95 |
| Availability | Uptime | 99.5% monthly |
| Security | Authentication | JWT, 1h expiry |

## 7. Constraints and Assumptions

**Constraints:**
- Single-region deployment (Jakarta) in MVP
- No mobile app in MVP — web only

**Assumptions:**
- Teams are 5–50 people
- English-only interface in MVP

## 8. Out of Scope

- Time tracking
- Billing and subscription management
- Native mobile applications
- Gantt charts

## 9. Glossary

| Entity | Canonical Name | Definition |
|--------|----------------|------------|
| Workspace | **Workspace** | A shared environment owned by an organisation, containing Members and Projects. |
| Member | **Member** | A registered individual who belongs to at least one Workspace with an assigned role. |
| Project | **Project** | A container for Tasks within a Workspace, owned by one Member. |
| Task | **Task** | A unit of work within a Project, assignable to a Member with a status and optional due date. |
| AuditLog | **AuditLog** | An immutable record of a state change event on any entity, with timestamp and actor. |
"""

INVALID_PRD_NO_GLOSSARY = """
# Product Requirements Document
## SomeApp

## 1. Product Overview
An app that does things.

## 4. Key Features

### Feature: Basic Feature
**Description:** Does something.
**Acceptance Criteria:**
- [ ] Users can do the thing

## 5. User Flows
1. User does the thing.
"""

INVALID_PRD_NO_FEATURES = """
# Product Requirements Document
## SomeApp

## 1. Product Overview
An app that does things.

## 9. Glossary

| Entity | Canonical Name | Definition |
|--------|----------------|------------|
| User | **User** | A person. |
"""

# ── Sample SDD (used in consistency tests) ────────────────────────────────
VALID_SDD = """
# System Design Document
## TaskFlow

## 3. Data Models

### Workspace
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Primary identifier |
| name | string | Yes | Display name |
| owner_member_id | UUID | Yes | FK to Member |

### Member
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Primary identifier |
| email | string | Yes | Unique login email |
| workspace_id | UUID | Yes | FK to Workspace |

### Project
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Primary identifier |
| workspace_id | UUID | Yes | FK to Workspace |
| owner_member_id | UUID | Yes | FK to Member |

### Task
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Primary identifier |
| project_id | UUID | Yes | FK to Project |
| assignee_member_id | UUID | No | FK to Member |
| status | string | Yes | open|in_progress|done |

### AuditLog
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Primary identifier |
| entity_type | string | Yes | e.g. Task |
| actor_member_id | UUID | Yes | FK to Member |

## 4. API Surface

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | /workspaces | Create workspace | Required |
| POST | /workspaces/{id}/members | Invite member | Required |
| GET  | /workspaces/{id}/dashboard | Manager dashboard | Required |
| POST | /projects | Create project | Required |
| POST | /tasks | Create task | Required |
| PATCH | /tasks/{id} | Update task status | Required |
"""

# Broken SDD: uses "User" instead of "Member" → entity_mismatch critical
BROKEN_SDD_WRONG_ENTITY = """
# System Design Document
## TaskFlow

## 3. Data Models

### Workspace
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Primary identifier |
| owner_user_id | UUID | Yes | FK to User |

### User
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Primary identifier |
| email | string | Yes | Login email |

### Task
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | Yes | Primary identifier |
| assigned_user_id | UUID | No | FK to User |
"""

# ── Sample API spec (used in consistency tests) ───────────────────────────
VALID_API_SPEC = """
openapi: "3.0.3"
info:
  title: TaskFlow API
  version: "1.0.0"
paths:
  /workspaces:
    post:
      summary: Create workspace
      responses:
        '201':
          description: Created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Workspace'
  /tasks:
    post:
      summary: Create task
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/TaskCreateRequest'
      responses:
        '201':
          description: Created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Task'
  /workspaces/{id}/dashboard:
    get:
      summary: Manager dashboard
      responses:
        '200':
          description: OK
components:
  schemas:
    Workspace:
      type: object
      properties:
        id:
          type: string
          format: uuid
    Member:
      type: object
      properties:
        id:
          type: string
          format: uuid
    Project:
      type: object
      properties:
        id:
          type: string
          format: uuid
    Task:
      type: object
      properties:
        id:
          type: string
          format: uuid
        status:
          type: string
          enum: [open, in_progress, done]
    AuditLog:
      type: object
      properties:
        id:
          type: string
          format: uuid
    TaskCreateRequest:
      type: object
      required: [title]
      properties:
        title:
          type: string
"""

CANONICAL_ENTITIES = ["Workspace", "Member", "Project", "Task", "AuditLog"]
