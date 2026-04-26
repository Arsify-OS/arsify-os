"""
Canonical test briefs.
Used by all three test layers (unit, integration, smoke).
Each brief is designed to exercise a specific domain pattern.
"""

# ── BRIEF A: SaaS / team tool ──────────────────────────────────────────────
BRIEF_SAAS = (
    "A project management tool for remote software teams. "
    "Teams create Workspaces, invite Members, and manage Projects. "
    "Each Project contains Tasks with status tracking, due dates, and assignees. "
    "Members can comment on Tasks and attach files. "
    "Managers see a dashboard with workload per Member and overdue Tasks. "
    "The product integrates with GitHub to auto-close Tasks when a PR is merged."
)

# ── BRIEF B: Marketplace ───────────────────────────────────────────────────
BRIEF_MARKETPLACE = (
    "A peer-to-peer marketplace for secondhand electronics. "
    "Sellers list Items with photos, condition rating, and asking price. "
    "Buyers can make Offers, message Sellers directly, and pay through the platform. "
    "The platform holds payment in escrow until the Buyer confirms receipt. "
    "Both parties leave Reviews after each Transaction. "
    "A Trust Score is calculated per User from their Review history."
)

# ── BRIEF C: API product ───────────────────────────────────────────────────
BRIEF_API_PRODUCT = (
    "A document parsing API for legal and financial teams. "
    "Clients upload Documents (PDF, DOCX) via API. "
    "The system extracts Clauses, identifies Parties, and detects Risk Flags. "
    "Each ParseJob has a status lifecycle: queued, processing, complete, failed. "
    "Results are available via webhook callback or polling endpoint. "
    "API Keys are scoped to an Organization with per-key rate limits and usage tracking."
)

# ── BRIEF D: Edge case — minimal brief (tests validation) ─────────────────
BRIEF_MINIMAL = (
    "A simple to-do list app for personal use. "
    "Users create Tasks with titles, due dates, and priority levels. "
    "Tasks can be marked done. Recurring Tasks reset automatically."
)

# ── BRIEF E: Edge case — very long brief (tests context limits) ───────────
BRIEF_LONG = (
    "An enterprise learning management system for large organizations. "
    "HR Admins create Learning Paths composed of Courses and Assessments. "
    "Employees are enrolled in Learning Paths by their Manager or automatically by Department rules. "
    "Each Course contains Lessons in video, text, or quiz format. "
    "Assessments have passing scores, attempt limits, and certificate generation on success. "
    "Managers track Completion Rates and Assessment Scores for their direct reports. "
    "The system integrates with Okta for SSO, Salesforce for employee records, "
    "and sends Slack notifications when Employees complete a Learning Path or fail an Assessment. "
    "Content Creators can build Courses using a drag-and-drop editor and preview them before publishing. "
    "The platform supports multiple Languages with per-Course locale settings."
)

ALL_BRIEFS = {
    "saas": BRIEF_SAAS,
    "marketplace": BRIEF_MARKETPLACE,
    "api_product": BRIEF_API_PRODUCT,
    "minimal": BRIEF_MINIMAL,
    "long": BRIEF_LONG,
}

# Expected minimum entity counts per brief (for validation tests)
EXPECTED_ENTITY_COUNTS = {
    "saas": 5,        # Workspace, Member, Project, Task, Comment
    "marketplace": 5, # Item, Seller, Buyer, Offer, Transaction, Review
    "api_product": 5, # Document, ParseJob, Clause, Party, RiskFlag, Organization, ApiKey
    "minimal": 2,     # Task, User
    "long": 6,        # LearningPath, Course, Assessment, Employee, Manager, Lesson
}
