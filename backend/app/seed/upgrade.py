"""Bring an existing demo database up to the current reference data. Safe to run repeatedly.

Run: ``python -m app.seed.upgrade`` (the container entrypoint runs it after migrations).

- Adds roles introduced since the database was seeded (Policy Owner, Chief HR Officer),
  grants the demo policy-owner account its role if it has none, and creates the demo
  Chief HR Officer account (``hr.chief``) and the employee repeat-risk model entry.
- Adds the workplace policies (HR-01..03) and rules, simulated time-clock history for the demo
  employees, and the generative-assistant model entry.
- Back-fills the procedural facts that the rules engine evaluates on synthetic cases
  seeded before the engine existed, and records which conditions matched on their findings.

Only synthetic cases are touched; real records are never given generated facts.
"""

import random

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, new_id, utcnow
from app.models import Finding, MistakeRule, ModelRegistry, Role, ServiceCase, User, UserRole
from app.pipeline.catalogue import generate_attributes
from app.seed import workplace_seed
from app.services import ai, rules_engine
from app.services.rbac import ROLE_CATALOGUE
from app.services.security import hash_password
from app.services.workforce import MODEL_NAME

BATCH = 2000


def ensure_roles(db: Session) -> list[str]:
    existing = set(db.scalars(select(Role.code)))
    added = []
    for code, spec in ROLE_CATALOGUE.items():
        if code not in existing:
            db.add(Role(id=new_id("ROL"), code=code, name=spec["name"], description=spec["description"]))
            added.append(code)
    db.flush()
    owner = db.scalar(select(User).where(User.username == "ops.policy"))
    if owner is not None:
        has_grants = db.scalar(select(func.count()).select_from(UserRole).where(UserRole.user_id == owner.id))
        if not has_grants:
            role_id = db.scalar(select(Role.id).where(Role.code == "policy_owner"))
            db.add(UserRole(id=new_id("URL"), user_id=owner.id, role_id=role_id, scope_type="global"))
            added.append("grant:ops.policy")
    if db.scalar(select(User.id).where(User.username == "hr.chief")) is None:
        chief = User(
            id=new_id("USR"),
            username="hr.chief",
            display_name="Demo Chief HR Officer",
            display_name_ar="رئيس الموارد البشرية (تجريبي)",
            password_hash=hash_password(get_settings().hr_chief_password),
            locale="en",
        )
        db.add(chief)
        db.flush()
        role_id = db.scalar(select(Role.id).where(Role.code == "hr_chief"))
        db.add(UserRole(id=new_id("URL"), user_id=chief.id, role_id=role_id, scope_type="global"))
        added.append("user:hr.chief")
    if db.scalar(select(ModelRegistry.id).where(ModelRegistry.name == MODEL_NAME)) is None:
        db.add(
            ModelRegistry(
                id=new_id("MDL"),
                name=MODEL_NAME,
                version="1.0",
                purpose="Indicative probability that a service type repeats for an employee in the next 90 days, "
                "fitted on bank history (peer rates, shrinkage, follow-up learning effects).",
                status="MONITORING",
                owner="Data & AI (demo)",
                limitations="Development planning only; never an input to disciplinary or pay decisions. Approval is "
                "simulated for the demo and fitted on synthetic data, so it demonstrates the method, not accuracy.",
                approved_at=utcnow(),
                last_run_at=utcnow(),
                latency_ms_p50=60,
            )
        )
        added.append("model:repeat-risk")
    if db.scalar(select(ModelRegistry.id).where(ModelRegistry.name == ai.REGISTRY_NAME)) is None:
        db.add(
            ModelRegistry(
                id=new_id("MDL"),
                name=ai.REGISTRY_NAME,
                version="1.0",
                purpose=ai.REGISTRY_PURPOSE,
                status="MONITORING",
                owner="Data & AI (demo)",
                limitations=ai.REGISTRY_LIMITATIONS,
                approved_at=utcnow(),
            )
        )
        added.append("model:generative-assistant")
    db.flush()
    return added


def backfill_attributes(db: Session) -> int:
    flagged = set(
        db.scalars(
            select(Finding.case_id)
            .join(MistakeRule, MistakeRule.id == Finding.rule_id)
            .where(MistakeRule.kind == "breach")
        )
    )
    done = 0
    while True:
        rows = db.execute(
            select(
                ServiceCase.id,
                ServiceCase.source_case_key,
                ServiceCase.case_type,
                ServiceCase.interaction_type,
                ServiceCase.complexity_band,
            )
            .where(ServiceCase.attributes.is_(None), ServiceCase.is_synthetic.is_(True))
            .limit(BATCH)
        ).all()
        if not rows:
            return done
        db.execute(
            update(ServiceCase),
            [
                {
                    "id": case_id,
                    "attributes": generate_attributes(
                        case_type, interaction, complexity, random.Random(f"attrs:{key}"), breach=case_id in flagged
                    ),
                }
                for case_id, key, case_type, interaction, complexity in rows
            ],
        )
        db.flush()
        done += len(rows)


def backfill_matched_conditions(db: Session) -> int:
    rules = {r.id: r for r in db.scalars(select(MistakeRule))}
    done = 0
    while True:
        rows = db.execute(
            select(Finding.id, Finding.rule_id, ServiceCase.attributes)
            .join(ServiceCase, ServiceCase.id == Finding.case_id)
            .where(Finding.matched_conditions.is_(None))
            .limit(BATCH)
        ).all()
        if not rows:
            return done
        db.execute(
            update(Finding),
            [
                {"id": fid, "matched_conditions": rules_engine.matched_detail(rules[rule_id].conditions, attrs)}
                for fid, rule_id, attrs in rows
            ],
        )
        db.flush()
        done += len(rows)


def main() -> None:
    with SessionLocal() as db:
        if not db.scalar(select(func.count()).select_from(User)):
            print("Database not seeded yet; nothing to upgrade.")
            return
        roles = ensure_roles(db)
        cases = backfill_attributes(db)
        findings = backfill_matched_conditions(db)
        roles += workplace_seed.ensure_for_existing(db)
        db.commit()
    print(
        f"Upgrade complete: roles/grants added {roles or 'none'}, case facts back-filled {cases}, findings {findings}."
    )


if __name__ == "__main__":
    main()
