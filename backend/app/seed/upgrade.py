"""Bring an existing demo database up to the current reference data. Safe to run repeatedly.

Run: ``python -m app.seed.upgrade`` (the container entrypoint runs it after migrations).

- Adds roles introduced since the database was seeded (e.g. Policy Owner) and grants the
  demo policy-owner account its role if it has none.
- Back-fills the procedural facts that the rules engine evaluates on synthetic cases
  seeded before the engine existed, and records which conditions matched on their findings.

Only synthetic cases are touched; real records are never given generated facts.
"""

import random

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal, new_id
from app.models import Finding, MistakeRule, Role, ServiceCase, User, UserRole
from app.pipeline.catalogue import generate_attributes
from app.services import rules_engine
from app.services.rbac import ROLE_CATALOGUE

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
        db.commit()
    print(
        f"Upgrade complete: roles/grants added {roles or 'none'}, case facts back-filled {cases}, findings {findings}."
    )


if __name__ == "__main__":
    main()
