"""Role-based access control and data-scope resolution.

The role catalogue is a *proposed* mapping that must be validated by the
bank's HR and organisational owners. Authorisation is always enforced on the
server; the frontend only uses the permission list to decide what to show.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OrgUnit

ROLE_CATALOGUE: dict[str, dict] = {
    "super_admin": {
        "name": "Super Admin",
        "description": "Manage roles, access policies, configuration, integrations, model/pipeline settings and audit views.",
    },
    "dept_head": {
        "name": "Department Head / Chief Officer",
        "description": "Aggregated department performance, trends, risk themes and approved reports.",
    },
    "regional_manager": {
        "name": "Regional Manager",
        "description": "Aggregated regional view and authorised branch comparisons.",
    },
    "branch_manager": {
        "name": "Branch Manager",
        "description": "Authorised branch cases, team learning plans and follow-up actions.",
    },
    "section_manager": {
        "name": "Section Manager / Unit Head",
        "description": "Team-level trends and assigned case reviews.",
    },
    "team_lead": {
        "name": "Team Lead / Senior Staff",
        "description": "Coaching tasks and authorised case details for their team.",
    },
    "employee": {
        "name": "Customer-facing Employee",
        "description": "Own findings, permitted evidence, acknowledgement/dispute, action plan and learning history.",
    },
    "hr_ld": {
        "name": "HR / Learning & Development",
        "description": "Training completion, coaching plans and approved learning metrics.",
    },
    "risk_compliance": {
        "name": "Risk / Compliance / Internal Audit",
        "description": "Reviewed cases, policy mappings, controls and audit trail according to mandate.",
    },
    "data_ai_ops": {
        "name": "Data / AI / IT Operations",
        "description": "Data quality, model versions, pipeline status and diagnostics; no case content.",
    },
    "analyst": {
        "name": "Read-only Analyst",
        "description": "Aggregated, de-identified reporting according to approval.",
    },
}

PERMISSIONS: dict[str, str] = {
    "dashboard.view": "View the overview dashboard (scoped aggregates)",
    "cases.view": "View case and finding details within scope",
    "evidence.view_restricted": "View restricted evidence references",
    "findings.review": "Record reviewer decisions on findings",
    "findings.respond": "Submit own acknowledgement / dispute",
    "actions.manage": "Create and update improvement actions within scope",
    "actions.update_own": "Update status of actions owned by self",
    "learning.view": "View learning profiles within scope",
    "learning.approve": "Approve proposed learning generations",
    "coaching.record": "Record coaching sessions",
    "insights.view": "View team / branch aggregated insights",
    "simulations.run": "Run approved aggregate scenarios",
    "reports.view": "View business reports",
    "reports.ops": "View data-quality and model reports",
    "ops.view": "View pipeline and model health detail",
    "ops.manage": "Pause / resume pipelines",
    "admin.view": "View administration screens",
    "admin.manage": "Change users, roles and integrations",
    "audit.view": "View the audit trail",
    "config.view": "View system configuration and run database connection / schema checks",
    "config.manage": "Change system configuration, database connections and apply schema changes",
}

_MANAGER_BASE = {"dashboard.view", "cases.view", "learning.view", "insights.view", "reports.view"}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "super_admin": set(PERMISSIONS),
    "dept_head": {"dashboard.view", "insights.view", "reports.view", "simulations.run"},
    "regional_manager": _MANAGER_BASE | {"simulations.run"},
    "branch_manager": _MANAGER_BASE
    | {"findings.review", "actions.manage", "learning.approve", "coaching.record", "evidence.view_restricted"},
    "section_manager": _MANAGER_BASE | {"findings.review", "actions.manage", "coaching.record"},
    "team_lead": {"dashboard.view", "cases.view", "learning.view", "actions.manage", "coaching.record"},
    "employee": {"dashboard.view", "cases.view", "findings.respond", "actions.update_own", "learning.view"},
    "hr_ld": {
        "dashboard.view",
        "learning.view",
        "learning.approve",
        "coaching.record",
        "actions.manage",
        "insights.view",
        "reports.view",
        "simulations.run",
    },
    "risk_compliance": {
        "dashboard.view",
        "cases.view",
        "evidence.view_restricted",
        "findings.review",
        "insights.view",
        "reports.view",
        "reports.ops",
        "simulations.run",
        "ops.view",
        "audit.view",
    },
    "data_ai_ops": {"dashboard.view", "reports.ops", "ops.view", "ops.manage", "config.view"},
    "analyst": {"dashboard.view", "insights.view", "reports.view"},
}


@dataclass(frozen=True)
class Grant:
    role_code: str
    scope_type: str
    scope_id: str | None


@dataclass
class Scope:
    """Data visibility for a permission: everything, a set of org units, or own records."""

    all: bool = False
    org_unit_ids: set[str] = field(default_factory=set)
    employee_ids: set[str] = field(default_factory=set)

    @property
    def empty(self) -> bool:
        return not self.all and not self.org_unit_ids and not self.employee_ids


def permissions_for(grants: list[Grant]) -> set[str]:
    perms: set[str] = set()
    for g in grants:
        perms |= ROLE_PERMISSIONS.get(g.role_code, set())
    return perms


def descendants(db: Session, root_ids: set[str]) -> set[str]:
    units = db.execute(select(OrgUnit.id, OrgUnit.parent_id)).all()
    children: dict[str | None, list[str]] = {}
    for uid, parent in units:
        children.setdefault(parent, []).append(uid)
    result: set[str] = set()
    stack = list(root_ids)
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(children.get(current, []))
    return result


def resolve_scope(db: Session, grants: list[Grant], permission: str, employee_id: str | None) -> Scope:
    scope = Scope()
    roots: set[str] = set()
    for g in grants:
        if permission not in ROLE_PERMISSIONS.get(g.role_code, set()):
            continue
        if g.scope_type == "global":
            return Scope(all=True)
        if g.scope_type == "self":
            if employee_id:
                scope.employee_ids.add(employee_id)
        elif g.scope_id:
            roots.add(g.scope_id)
    if roots:
        scope.org_unit_ids = descendants(db, roots)
    return scope
