"""Seed the database with clearly-labelled SYNTHETIC demo data.

Run: ``python -m app.seed.seed_mock_data [--reset]``

Every name and identifier is fictional or pseudonymous. Synthetic records must
not be used to claim model accuracy or to judge real employees.
"""

import argparse
import hashlib
import math
import random
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, SessionLocal, engine, new_id, utcnow
from app.models import (
    AuditEvent,
    CoachingSession,
    EmployeeProfile,
    EmployeeResponse,
    EvidenceRef,
    Finding,
    FollowUpEvaluation,
    ImprovementAction,
    IngestionRun,
    MistakeRule,
    ModelRegistry,
    ModelRun,
    OrgUnit,
    Pipeline,
    PolicyVersion,
    QuarantinedRecord,
    ReviewDecision,
    Role,
    ServiceCase,
    ServiceHeartbeat,
    SourceSystem,
    TrainingRecord,
    User,
    UserRole,
)
from app.pipeline.catalogue import ACTION_TEMPLATES, CASE_TYPES, INTERACTION_TYPES, explanation
from app.services import learning
from app.services.rbac import ROLE_CATALOGUE
from app.services.security import hash_password

HISTORY_DAYS = 270
RNG_SEED = 20261025

REGIONS = [
    ("NORTH", "North Region", "إقليم الشمال", 2),
    ("CENTRAL", "Central Region", "إقليم الوسط", 3),
    ("SOUTH", "South Region", "إقليم الجنوب", 2),
    ("GAZA", "Gaza Region", "إقليم غزة", 1),
]
SECTIONS = [
    ("TEL", "Tellers", "الصرّافون", "Teller"),
    ("CSO", "Customer Service", "خدمة العملاء", "Customer Service Officer"),
]
CC_SECTIONS = [
    ("VOICE", "Inbound Voice", "الاتصال الهاتفي", "Contact Centre Agent"),
    ("CHAT", "Digital Chat", "المحادثة الرقمية", "Digital Service Agent"),
]
SECTION_CASE_TYPES = {
    "TEL": ["cash_transaction", "transfers", "account_opening", "general_inquiry"],
    "CSO": ["account_opening", "card_services", "complaint_handling", "loan_inquiry", "general_inquiry"],
    "VOICE": ["complaint_handling", "general_inquiry", "card_services", "transfers"],
    "CHAT": ["general_inquiry", "complaint_handling", "loan_inquiry"],
}
SOURCE_FOR_CASE = {
    "complaint_handling": "COMPLAINTS",
    "general_inquiry": "CRM",
    "card_services": "CRM",
    "loan_inquiry": "CRM",
}


class Seeder:
    def __init__(self, db: Session):
        self.db = db
        self.rng = random.Random(RNG_SEED)
        self.now = utcnow().replace(microsecond=0)
        self.start = self.now - timedelta(days=HISTORY_DAYS)
        self.settings = get_settings()
        self.units: dict[str, OrgUnit] = {}
        self.users: dict[str, User] = {}
        self.roles: dict[str, Role] = {}
        self.sources: dict[str, SourceSystem] = {}
        self.policies: dict[str, PolicyVersion] = {}
        self.rules: dict[str, MistakeRule] = {}
        self.models: dict[str, ModelRegistry] = {}
        self.employees: list[tuple[EmployeeProfile, str]] = []  # (profile, section code)
        self.section_leads: dict[str, User] = {}
        self._pending: dict[str, list] = {}

    # ------------------------------------------------------------------ helpers
    def add(self, obj):
        # Buffered per table and written in foreign-key order by flush(): most models
        # have no ORM relationships, so the unit of work cannot order them itself.
        self._pending.setdefault(obj.__table__.name, []).append(obj)
        return obj

    def flush(self) -> None:
        for table in Base.metadata.sorted_tables:
            batch = self._pending.pop(table.name, [])
            if batch:
                self.db.add_all(batch)
                self.db.flush()

    def unit(self, code: str, unit_type: str, name: str, name_ar: str, parent: OrgUnit | None) -> OrgUnit:
        ou = self.add(
            OrgUnit(
                id=new_id("ORG"),
                code=code,
                unit_type=unit_type,
                name=name,
                name_ar=name_ar,
                parent_id=parent.id if parent else None,
            )
        )
        self.units[code] = ou
        return ou

    def user(self, username: str, name: str, name_ar: str, grants: list[tuple[str, str, str | None]]) -> User:
        u = self.add(
            User(
                id=new_id("USR"),
                username=username,
                display_name=name,
                display_name_ar=name_ar,
                password_hash=self._password_hash,
                locale="en",
                created_at=self.start,
            )
        )
        for role_code, scope_type, scope_code in grants:
            self.add(
                UserRole(
                    id=new_id("URL"),
                    user_id=u.id,
                    role_id=self.roles[role_code].id,
                    scope_type=scope_type,
                    scope_id=self.units[scope_code].id if scope_code else None,
                )
            )
        self.users[username] = u
        return u

    def at(self, base: datetime, min_days: float, max_days: float) -> datetime:
        return base + timedelta(days=self.rng.uniform(min_days, max_days))

    # --------------------------------------------------------------- reference
    def seed_reference(self) -> None:
        self._password_hash = hash_password(self.settings.demo_password)
        for code, spec in ROLE_CATALOGUE.items():
            self.roles[code] = self.add(
                Role(id=new_id("ROL"), code=code, name=spec["name"], description=spec["description"])
            )

        bank = self.unit("BANK", "bank", "Bank (demo)", "البنك (تجريبي)", None)
        retail = self.unit("DEP-RETAIL", "department", "Retail Banking", "الخدمات المصرفية للأفراد", bank)
        contact = self.unit("DEP-CC", "department", "Contact Centre", "مركز الاتصال", bank)
        ops = self.unit("DEP-OPS", "department", "Operations & Policy", "العمليات والسياسات", bank)
        self.unit("DEP-CMP", "department", "Risk & Compliance", "المخاطر والامتثال", bank)

        for rcode, rname, rname_ar, branch_count in REGIONS:
            region = self.unit(f"REG-{rcode}", "region", rname, rname_ar, retail)
            for i in range(1, branch_count + 1):
                bcode = f"BR-{rcode[0]}{i:02d}"
                branch = self.unit(
                    bcode, "branch", f"{rname.split()[0]} Branch {i:02d}", f"فرع {rname_ar.split()[1]} {i:02d}", region
                )
                for scode, sname, sname_ar, _ in SECTIONS:
                    self.unit(
                        f"{bcode}-{scode}",
                        "section",
                        f"{branch.name} · {sname}",
                        f"{branch.name_ar} · {sname_ar}",
                        branch,
                    )
        for scode, sname, sname_ar, _ in CC_SECTIONS:
            self.unit(f"CC-{scode}", "section", f"Contact Centre · {sname}", f"مركز الاتصال · {sname_ar}", contact)

        source_specs = [
            ("CRM", "CRM case management (simulated)", "crm", "Retail Operations", True),
            ("QA", "Quality-assurance reviews (simulated)", "qa", "Service Quality Unit", True),
            ("COMPLAINTS", "Complaint management (simulated)", "complaints", "Customer Experience", True),
            ("CALLMETA", "Call-centre metadata (simulated)", "telephony", "Contact Centre IT", True),
            ("LMS", "Learning management system (simulated)", "lms", "Learning & Development", True),
            ("POLICY", "Policy & procedure catalogue (simulated)", "policy", "Operations & Policy", True),
            ("TRANSCRIPTS", "Interaction transcripts (NOT approved)", "transcripts", "Contact Centre IT", False),
        ]
        for code, name, stype, owner, approved in source_specs:
            self.sources[code] = self.add(
                SourceSystem(
                    id=new_id("SRC"),
                    code=code,
                    name=name,
                    system_type=stype,
                    owner=owner,
                    enabled=approved,
                    approved_for_use=approved,
                )
            )

        for case_type, spec in CASE_TYPES.items():
            pcode, title, title_ar = spec["policy"]
            old = self.add(
                PolicyVersion(
                    id=new_id("POL"),
                    policy_code=pcode,
                    version="1.0",
                    title=title,
                    title_ar=title_ar,
                    summary=f"Superseded version of {title}.",
                    summary_ar=f"إصدار سابق من: {title_ar}.",
                    effective_from=self.start - timedelta(days=400),
                    effective_to=self.start + timedelta(days=60),
                    owner_unit_id=ops.id,
                    approved_at=self.start - timedelta(days=410),
                )
            )
            current = self.add(
                PolicyVersion(
                    id=new_id("POL"),
                    policy_code=pcode,
                    version="1.1",
                    title=title,
                    title_ar=title_ar,
                    summary=spec["expected"][0],
                    summary_ar=spec["expected"][1],
                    effective_from=self.start + timedelta(days=60),
                    owner_unit_id=ops.id,
                    approved_at=self.start + timedelta(days=50),
                )
            )
            self.policies[case_type] = current
            self.policies[f"{case_type}:old"] = old
            for pol, ver in ((old, "1"), (current, "2")):
                rule = self.add(
                    MistakeRule(
                        id=new_id("RUL"),
                        rule_code=spec["rule"],
                        version=ver,
                        category=case_type,
                        policy_version_id=pol.id,
                        description=spec["description"][0],
                        description_ar=spec["description"][1],
                        expected_action=spec["expected"][0],
                        expected_action_ar=spec["expected"][1],
                        severity=spec["severity"],
                        active=pol is current,
                    )
                )
                self.rules[f"{case_type}:{ver}"] = rule

        model_specs = [
            (
                "Procedure deviation rules engine",
                "2.3",
                "DEPLOYED",
                "Applies versioned policy rules to structured case metadata.",
                "Rules only flag potential findings; every finding requires human review.",
                38,
                0.01,
                0.04,
                0.11,
            ),
            (
                "Complaint category classifier",
                "0.4",
                "VALIDATION",
                "Suggests complaint categories from approved structured fields.",
                "Under validation; outputs hidden from case decisions.",
                120,
                0.06,
                0.09,
                None,
            ),
            (
                "QA sampling prioritiser",
                "1.1",
                "MONITORING",
                "Prioritises interactions for human QA sampling.",
                "Prioritisation only; does not classify mistakes.",
                55,
                0.02,
                0.07,
                0.18,
            ),
            (
                "Call metadata anomaly detector",
                "0.9",
                "DEGRADED",
                "Flags unusual call-handling patterns for QA review.",
                "Drift detected after telephony change; outputs held for review.",
                210,
                0.14,
                0.31,
                0.27,
            ),
            (
                "Recurrence scenario simulator",
                "0.1",
                "DEVELOPMENT",
                "Illustrative aggregate scenario estimates.",
                "Illustrative; not validated; aggregate only; employee-level use disabled.",
                90,
                0.0,
                None,
                None,
            ),
            (
                "Recurrence risk estimator",
                "1.0",
                "APPROVED",
                "Aggregate case-level recurrence estimate (approval simulated).",
                "Approval status is simulated for the demo and confers no real approval.",
                75,
                0.03,
                0.05,
                None,
            ),
            (
                "Transcript summariser",
                "0.2",
                "SUSPENDED",
                "Summarises transcripts for reviewers.",
                "Suspended: transcript source is not approved for use.",
                None,
                None,
                None,
                None,
            ),
            (
                "Legacy keyword flagger",
                "1.0",
                "RETIRED",
                "Keyword-based flagging (replaced by rules engine).",
                "Retired due to high false-positive rate.",
                None,
                None,
                None,
                None,
            ),
        ]
        for name, version, status, purpose, limits, latency, missing, drift, override in model_specs:
            self.models[name] = self.add(
                ModelRegistry(
                    id=new_id("MDL"),
                    name=name,
                    version=version,
                    purpose=purpose,
                    status=status,
                    owner="Data & AI (demo)",
                    limitations=limits,
                    latency_ms_p50=latency,
                    missing_input_rate=missing,
                    drift_score=drift,
                    override_rate=override,
                    state_changed_at=self.now - timedelta(days=self.rng.randint(2, 40)),
                    approved_at=self.now - timedelta(days=120)
                    if status in ("APPROVED", "DEPLOYED", "MONITORING", "DEGRADED")
                    else None,
                    last_validation_at=self.now - timedelta(days=self.rng.randint(10, 90))
                    if status != "DEVELOPMENT"
                    else None,
                    last_run_at=self.now - timedelta(minutes=self.rng.randint(1, 30))
                    if status in ("DEPLOYED", "MONITORING", "DEGRADED")
                    else None,
                )
            )

    # ---------------------------------------------------------------- people
    def seed_people(self) -> None:
        self.user("superadmin", "Demo Super Admin", "مدير النظام (تجريبي)", [("super_admin", "global", None)])
        self.user(
            "dept.head",
            "Demo Head of Retail",
            "رئيس دائرة الأفراد (تجريبي)",
            [("dept_head", "department", "DEP-RETAIL")],
        )
        self.user(
            "regional.north",
            "Demo North Regional Manager",
            "مدير إقليم الشمال (تجريبي)",
            [("regional_manager", "region", "REG-NORTH")],
        )
        self.user(
            "branch.n01",
            "Demo Branch Manager N01",
            "مدير فرع الشمال 01 (تجريبي)",
            [("branch_manager", "branch", "BR-N01")],
        )
        self.user(
            "section.n01",
            "Demo Section Manager N01 Tellers",
            "مدير قسم الصرافين (تجريبي)",
            [("section_manager", "section", "BR-N01-TEL")],
        )
        self.user("hr.ld", "Demo L&D Partner", "شريك التعلم والتطوير (تجريبي)", [("hr_ld", "global", None)])
        self.user(
            "risk.compliance",
            "Demo Compliance Reviewer",
            "مراجع الامتثال (تجريبي)",
            [("risk_compliance", "global", None)],
        )
        self.user(
            "data.ops",
            "Demo Data & AI Ops",
            "عمليات البيانات والذكاء الاصطناعي (تجريبي)",
            [("data_ai_ops", "global", None)],
        )
        self.user("analyst", "Demo Read-only Analyst", "محلل للقراءة فقط (تجريبي)", [("analyst", "global", None)])
        self.user("ops.policy", "Demo Policy Owner", "مالك السياسة (تجريبي)", [])

        counter = 1001
        sections = [u for u in self.units.values() if u.unit_type == "section"]
        for section in sections:
            scode = section.code.split("-")[-1]
            title = next(t for c, *_rest, t in SECTIONS + CC_SECTIONS if c == scode)
            lead_username = f"lead.{section.code.lower()}"
            lead = self.user(
                lead_username,
                f"Demo Team Lead {section.code}",
                f"قائد فريق {section.code} (تجريبي)",
                [("team_lead", "section", section.code)],
            )
            self.section_leads[section.id] = lead
            for _ in range(self.rng.randint(4, 6)):
                profile = self.add(
                    EmployeeProfile(
                        id=new_id("EMP"),
                        pseudonym=f"E-{counter}",
                        org_unit_id=section.id,
                        role_title=title,
                        start_date=date(2019 + self.rng.randint(0, 6), self.rng.randint(1, 12), 1),
                    )
                )
                self.employees.append((profile, scode))
                counter += 1

        # The demo employee account is linked to the first teller in North Branch 01.
        first = next(p for p, _ in self.employees if p.org_unit_id == self.units["BR-N01-TEL"].id)
        emp_user = self.user(
            "employee.demo",
            f"Demo Employee {first.pseudonym}",
            f"موظف تجريبي {first.pseudonym}",
            [("employee", "self", None)],
        )
        first.user_id = emp_user.id
        self.flush()

    # ------------------------------------------------------------- activity
    def seed_history(self) -> None:
        reviewers = {
            "branch": self.users["branch.n01"],
            "risk": self.users["risk.compliance"],
            "section": self.users["section.n01"],
        }
        hr = self.users["hr.ld"]
        policy_owner = self.users["ops.policy"]

        for profile, scode in self.employees:
            unit_id = profile.org_unit_id
            lead = self.section_leads[unit_id]
            in_n01 = unit_id in {u.id for code, u in self.units.items() if code.startswith("BR-N01")}
            reviewer = reviewers["branch"] if in_n01 else self.rng.choice([reviewers["risk"], reviewers["section"]])
            base_rate = self.rng.uniform(0.02, 0.10)
            responsiveness = self.rng.uniform(0.25, 0.9)
            rate_by_type = {ct: base_rate * self.rng.uniform(0.6, 1.4) for ct in SECTION_CASE_TYPES[scode]}
            cases_per_day = self.rng.uniform(0.35, 0.8)
            day = self.start
            seq = 0
            while day < self.now:
                day += timedelta(days=-math.log(1 - self.rng.random()) / cases_per_day)
                if day >= self.now:
                    break
                if day.weekday() == 4:  # Friday: branches closed in the demo calendar
                    continue
                seq += 1
                case_type = self.rng.choice(SECTION_CASE_TYPES[scode])
                source = self.sources[
                    "CALLMETA" if scode in ("VOICE", "CHAT") else SOURCE_FOR_CASE.get(case_type, "QA")
                ]
                is_old_policy = day < self.policies[case_type].effective_from
                policy = self.policies[f"{case_type}:old"] if is_old_policy else self.policies[case_type]
                case = self.add(
                    ServiceCase(
                        id=new_id("CS"),
                        source_system_id=source.id,
                        source_case_key=f"{profile.pseudonym}-{seq:05d}",
                        employee_id=profile.id,
                        org_unit_id=unit_id,
                        case_type=case_type,
                        interaction_type="phone"
                        if scode == "VOICE"
                        else "chat"
                        if scode == "CHAT"
                        else self.rng.choice(INTERACTION_TYPES[:1] * 3 + INTERACTION_TYPES[2:]),
                        occurred_at=day,
                        complexity_band=self.rng.choices(("low", "medium", "high"), (5, 3, 2))[0],
                        policy_version_id=policy.id,
                        created_at=day + timedelta(hours=2),
                    )
                )
                if self.rng.random() < rate_by_type[case_type]:
                    learned = self._seed_finding(
                        case, policy, is_old_policy, profile, lead, reviewer, hr, policy_owner, responsiveness
                    )
                    if learned:
                        rate_by_type[case_type] *= 1 - responsiveness * 0.7
            self.flush()

    def _seed_finding(
        self, case, policy, is_old_policy, profile, lead, reviewer, hr, policy_owner, responsiveness
    ) -> bool:
        rng = self.rng
        spec = CASE_TYPES[case.case_type]
        rule = self.rules[f"{case.case_type}:{'1' if is_old_policy else '2'}"]
        created = self.at(case.occurred_at, 0.5, 3)
        if created > self.now:
            created = self.now - timedelta(minutes=5)
        model = self.models["Procedure deviation rules engine"]
        method = "rule"
        if case.case_type == "complaint_handling" and rng.random() < 0.3:
            model, method = self.models["QA sampling prioritiser"], "model"
        confidence = round(rng.uniform(0.62, 0.97), 2)
        finding = self.add(
            Finding(
                id=new_id("FND"),
                case_id=case.id,
                rule_id=rule.id,
                status="POTENTIAL",
                severity=rule.severity,
                reason_code=spec["rule"],
                observed_action=spec["observed"][0],
                observed_action_ar=spec["observed"][1],
                explanation=explanation(case.case_type, policy.version, "en"),
                explanation_ar=explanation(case.case_type, policy.version, "ar"),
                detection_method=method,
                model_id=model.id,
                confidence=confidence,
                created_at=created,
            )
        )
        self.add(
            ModelRun(
                id=new_id("MRN"),
                model_id=model.id,
                case_id=case.id,
                run_at=created,
                output_summary=f"potential:{spec['rule']}",
                confidence=confidence,
                latency_ms=rng.randint(20, 160),
                review_status="pending",
            )
        )
        for ev_type, access in (("qa_review_form", "internal"), ("system_audit_event", "restricted")):
            ref = f"{ev_type}://{case.source_case_key}/{rng.randint(1000, 9999)}"
            self.add(
                EvidenceRef(
                    id=new_id("EVD"),
                    case_id=case.id,
                    evidence_type=ev_type,
                    secure_reference=ref,
                    content_hash=hashlib.sha256(ref.encode()).hexdigest(),
                    access_class=access,
                    summary="Synthetic evidence pointer — content stays in the source system.",
                    created_at=created,
                )
            )

        age_days = (self.now - created).days
        employee_user_id = profile.user_id

        # Employee perspective before feedback (self-reported, never inferred).
        awareness = rng.choices(("recognized", "not_recognized", "unsure", "disagree"), (35, 35, 18, 12))[0]
        if age_days >= 2 and rng.random() < 0.88:
            self.add(
                EmployeeResponse(
                    id=new_id("RSP"),
                    finding_id=finding.id,
                    stage="before_feedback",
                    awareness_state=awareness,
                    contextual_factors=rng.sample(
                        ["queue_pressure", "unclear_guidance", "system_slow", "customer_urgency"], k=rng.randint(0, 2)
                    ),
                    response_text="Synthetic demo response.",
                    requested_review=awareness == "disagree",
                    submitted_by=employee_user_id,
                    submitted_at=self.at(created, 0.2, 2),
                )
            )

        if age_days < 5:
            return False  # still awaiting review

        decided = self.at(created, 2, 6)
        roll = rng.random()
        if awareness == "disagree" and roll < 0.45:
            decision = "dispute_upheld"
        elif roll < 0.12:
            decision = "dismiss"
        elif roll < 0.2:
            decision = "amend"
        else:
            decision = "confirm"
        factors = spec["factors"]
        factor = (
            rng.choices(list(factors), list(factors.values()))[0]
            if decision in ("confirm", "amend")
            else "undetermined"
        )
        status = {"confirm": "CONFIRMED", "amend": "AMENDED", "dismiss": "DISMISSED", "dispute_upheld": "DISMISSED"}[
            decision
        ]
        self.add(
            ReviewDecision(
                id=new_id("REV"),
                finding_id=finding.id,
                decision=decision,
                reviewer_id=reviewer.id,
                decided_at=decided,
                rationale={
                    "confirm": "Evidence supports the finding; policy applied as written.",
                    "amend": "Finding confirmed with reduced severity given context.",
                    "dismiss": "Evidence does not support the finding.",
                    "dispute_upheld": "Employee's dispute upheld; guidance was ambiguous.",
                }[decision],
                policy_clear=factor != "policy_ambiguity",
                evidence_supports=decision in ("confirm", "amend"),
                system_issue_contributed=factor == "system_issue",
                contributing_factor=factor,
                amended_severity="low" if decision == "amend" else None,
            )
        )
        finding.status = status
        finding.contributing_factor = factor
        finding.reviewed_by = reviewer.id
        finding.reviewed_at = decided
        if decision == "amend":
            finding.severity = "low"
        if status == "DISMISSED":
            return False

        if age_days >= 8 and rng.random() < 0.9:
            self.add(
                EmployeeResponse(
                    id=new_id("RSP"),
                    finding_id=finding.id,
                    stage="after_feedback",
                    understood_after_feedback=rng.random() < 0.65 + responsiveness * 0.35,
                    response_text="Synthetic reflection after feedback.",
                    submitted_by=employee_user_id,
                    submitted_at=self.at(decided, 0.5, 3),
                )
            )

        learned = False
        action_types = ["coaching", rng.choice(["training", "job_aid", "practice"])]
        if factor == "policy_ambiguity":
            action_types.append("policy_clarification")
        if factor == "system_issue":
            action_types.append("system_fix")
        all_done = True
        for a_type in action_types:
            owner = policy_owner if a_type in ("policy_clarification", "system_fix") else lead
            due = decided + timedelta(days=rng.randint(10, 21))
            done_prob = 0.55 + responsiveness * 0.4
            completed = None
            status_a = "planned"
            if due < self.now or rng.random() < 0.3:
                if rng.random() < done_prob:
                    completed = min(self.at(decided, 3, 22), self.now - timedelta(hours=1))
                    status_a = "completed"
                elif rng.random() < 0.5:
                    status_a = "in_progress"
            if completed is None:
                all_done = False
            self.add(
                ImprovementAction(
                    id=new_id("ACT"),
                    finding_id=finding.id,
                    action_type=a_type,
                    description=ACTION_TEMPLATES[a_type][0],
                    owner_id=owner.id,
                    due_at=due,
                    status=status_a,
                    completed_at=completed,
                    completion_evidence_ref=f"lms://completion/{finding.id}" if completed else None,
                    created_by=reviewer.id,
                    created_at=decided,
                )
            )
            if a_type == "training" and completed:
                self.add(
                    TrainingRecord(
                        id=new_id("TRN"),
                        employee_id=profile.id,
                        course_code=f"REF-{spec['policy'][0]}",
                        related_finding_id=finding.id,
                        status="completed",
                        score=round(rng.uniform(55, 100) * (0.75 + responsiveness * 0.25), 1),
                        completed_at=completed,
                        source_system_id=self.sources["LMS"].id,
                        created_at=decided,
                    )
                )
            if a_type == "coaching" and completed:
                outcome = rng.choices(
                    ("discussed", "practiced", "demonstrated", "needs_follow_up"),
                    (2, 3 + responsiveness * 4, 1 + responsiveness * 4, 2),
                )[0]
                self.add(
                    CoachingSession(
                        id=new_id("COA"),
                        employee_id=profile.id,
                        manager_id=lead.id,
                        related_finding_id=finding.id,
                        session_at=completed,
                        outcome_code=outcome,
                        reflection="Synthetic coaching reflection.",
                    )
                )
                learned = learned or outcome in ("practiced", "demonstrated")
        return learned and all_done

    def seed_follow_ups(self) -> None:
        rows = self.db.execute(
            select(
                Finding.id, ServiceCase.employee_id, ServiceCase.case_type, ServiceCase.occurred_at, Finding.status
            ).join(ServiceCase, ServiceCase.id == Finding.case_id)
        ).all()
        by_key: dict[tuple, list] = {}
        for r in rows:
            by_key.setdefault((r.employee_id, r.case_type), []).append(r)
        case_counts = {}
        for emp_id, ctype, occurred in self.db.execute(
            select(ServiceCase.employee_id, ServiceCase.case_type, ServiceCase.occurred_at)
        ):
            case_counts.setdefault((emp_id, ctype), []).append(occurred)
        window = learning.FOLLOW_UP_DAYS
        for key, items in by_key.items():
            for f in items:
                if f.status not in ("CONFIRMED", "AMENDED") or f.occurred_at + timedelta(days=window) > self.now:
                    continue
                end = f.occurred_at + timedelta(days=window)
                comparable = sum(1 for t in case_counts.get(key, []) if f.occurred_at < t <= end)
                recurrences = sum(
                    1
                    for o in items
                    if o.id != f.id and o.status != "DISMISSED" and f.occurred_at < o.occurred_at <= end
                )
                self.add(
                    FollowUpEvaluation(
                        id=new_id("FUP"),
                        finding_id=f.id,
                        window_days=window,
                        comparable_cases=comparable,
                        recurrences=recurrences,
                        recurred=recurrences > 0,
                        evaluated_at=end,
                    )
                )

    def seed_generations(self) -> None:
        approver = self.users["hr.ld"]
        for profile, _ in self.employees:
            evidence = learning.load_evidence(self.db, profile.id)
            checkpoint = self.start + timedelta(days=45)
            while checkpoint < self.now - timedelta(days=7):
                learning.refresh_generation(
                    self.db, profile.id, as_of=checkpoint, approver_id=approver.id, evidence=evidence
                )
                checkpoint += timedelta(days=30)
            # Latest evaluation: most approved, some left pending manager/HR approval.
            pending = self.rng.random() < 0.2
            learning.refresh_generation(
                self.db,
                profile.id,
                as_of=self.now - timedelta(hours=1),
                approver_id=None if pending else approver.id,
                evidence=evidence,
            )
        self.flush()

    def seed_ops(self) -> None:
        specs = [
            ("qa-reviews", "QA review outcomes", "QA", "HEALTHY", "stable", 120, 30),
            ("crm-cases", "CRM case metadata", "CRM", "RUNNING", "stable", 90, 20),
            ("complaints", "Complaint records", "COMPLAINTS", "DEGRADED", "flaky", 180, 45),
            ("call-metadata", "Call-centre metadata", "CALLMETA", "FAILED", "failing", 240, 60),
            ("lms-training", "LMS training completions", "LMS", "STALE", "slow", 6 * 3600, 240),
            ("policy-catalogue", "Policy catalogue sync", "POLICY", "HEALTHY", "stable", 300, 1440),
            ("transcripts", "Interaction transcripts", "TRANSCRIPTS", "PAUSED", "stable", 600, 60),
        ]
        for code, name, src, state, profile, schedule, sla in specs:
            last_success = self.now - timedelta(seconds=schedule)
            if state == "STALE":
                last_success = self.now - timedelta(hours=30)
            if state == "FAILED":
                last_success = self.now - timedelta(minutes=95)
            if state == "PAUSED":
                last_success = self.now - timedelta(days=12)
            pipe = self.add(
                Pipeline(
                    id=new_id("PIP"),
                    code=code,
                    name=name,
                    source_system_id=self.sources[src].id,
                    state=state,
                    state_changed_at=self.now - timedelta(minutes=self.rng.randint(5, 90)),
                    last_run_at=self.now - timedelta(minutes=2),
                    last_success_at=last_success,
                    next_run_at=self.now + timedelta(hours=8)
                    if state == "STALE"
                    else self.now + timedelta(seconds=schedule),
                    schedule_seconds=schedule,
                    freshness_sla_minutes=sla,
                    owner=f"{self.sources[src].owner} (demo)",
                    runbook_url=f"https://runbooks.example.invalid/bop-evolve/{code}",
                    demo_profile=profile,
                    queue_lag_seconds=self.rng.randint(0, 40) if state != "DEGRADED" else 380,
                    last_error={
                        "FAILED": "Upstream API returned 503 (simulated)",
                        "DEGRADED": "Rejected-record rate above 10% (simulated)",
                        "STALE": "No successful sync within freshness SLA (simulated)",
                        "PAUSED": "Paused: source not approved for use",
                    }.get(state),
                    last_request_id=new_id("REQ"),
                )
            )
            if state == "PAUSED":
                continue
            t = self.now - timedelta(hours=24)
            step = timedelta(seconds=max(schedule, 1800))
            while t < self.now - step:
                read = self.rng.randint(20, 120)
                rejected = self.rng.randint(0, 3) if profile == "stable" else self.rng.randint(2, 15)
                dup = self.rng.randint(0, 4)
                failed = profile == "failing" and self.rng.random() < 0.3
                run = self.add(
                    IngestionRun(
                        id=new_id("RUN"),
                        pipeline_id=pipe.id,
                        source_system_id=pipe.source_system_id,
                        started_at=t,
                        finished_at=t + timedelta(seconds=self.rng.randint(4, 40)),
                        status="failed" if failed else "partial" if rejected > 8 else "succeeded",
                        records_read=0 if failed else read,
                        records_written=0 if failed else read - rejected - dup,
                        records_rejected=0 if failed else rejected,
                        records_duplicated=0 if failed else dup,
                        duration_ms=self.rng.randint(800, 9000),
                        request_id=new_id("REQ"),
                        error_summary="Upstream API returned 503 (simulated)" if failed else None,
                    )
                )
                if not failed and rejected:
                    self.add(
                        QuarantinedRecord(
                            id=new_id("QRN"),
                            ingestion_run_id=run.id,
                            source_record_key=f"SRC-{self.rng.randint(10000, 99999)}",
                            reason=self.rng.choice(
                                [
                                    "missing_required_field:employee_ref",
                                    "schema_mismatch:occurred_at",
                                    "unknown_case_type",
                                ]
                            ),
                            payload_redacted={"fields_present": ["case_type", "occurred_at"]},
                            created_at=t,
                        )
                    )
                t += step
        self.add(ServiceHeartbeat(name="pipeline-worker", last_beat_at=self.now, detail={"status": "seeded"}))
        self.add(
            AuditEvent(
                id=new_id("AUD"),
                actor_user_id=self.users["superadmin"].id,
                action="seed.completed",
                resource_type="system",
                metadata_redacted={"synthetic": True, "employees": len(self.employees)},
            )
        )

    def run(self) -> None:
        self.seed_reference()
        self.flush()
        self.seed_people()
        self.seed_ops()
        self.flush()
        self.seed_history()
        self.flush()
        self.seed_follow_ups()
        self.flush()
        self.seed_generations()
        self.db.commit()


def is_seeded(db: Session) -> bool:
    return (db.scalar(select(func.count()).select_from(User)) or 0) > 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed BOP Evolve with synthetic demo data")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate all tables first (destroys data)")
    parser.add_argument("--if-empty", action="store_true", help="Only seed when the database has no users")
    args = parser.parse_args()

    if args.reset:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if is_seeded(db):
            if args.if_empty:
                print("Database already seeded; skipping.")
                return
            raise SystemExit("Database already contains data. Use --reset to recreate it.")
        Seeder(db).run()
        cases = db.scalar(select(func.count()).select_from(ServiceCase))
        findings = db.scalar(select(func.count()).select_from(Finding))
        print(f"Seeded synthetic demo data: {cases} cases, {findings} findings.")


if __name__ == "__main__":
    main()
