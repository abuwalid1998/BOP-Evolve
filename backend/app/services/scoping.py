from sqlalchemy import false, or_, true
from sqlalchemy.orm import Session

from app.models import EmployeeProfile, OrgUnit, ServiceCase
from app.services.rbac import Scope


def case_condition(scope: Scope):
    if scope.all:
        return true()
    conds = []
    if scope.org_unit_ids:
        conds.append(ServiceCase.org_unit_id.in_(scope.org_unit_ids))
    if scope.employee_ids:
        conds.append(ServiceCase.employee_id.in_(scope.employee_ids))
    return or_(*conds) if conds else false()


def employee_condition(scope: Scope):
    if scope.all:
        return true()
    conds = []
    if scope.org_unit_ids:
        conds.append(EmployeeProfile.org_unit_id.in_(scope.org_unit_ids))
    if scope.employee_ids:
        conds.append(EmployeeProfile.id.in_(scope.employee_ids))
    return or_(*conds) if conds else false()


def case_in_scope(scope: Scope, case: ServiceCase) -> bool:
    return scope.all or case.org_unit_id in scope.org_unit_ids or case.employee_id in scope.employee_ids


def employee_in_scope(scope: Scope, employee: EmployeeProfile) -> bool:
    return scope.all or employee.org_unit_id in scope.org_unit_ids or employee.id in scope.employee_ids


def org_path(db: Session, unit_id: str) -> list[OrgUnit]:
    """Ancestors from the bank down to ``unit_id``."""
    path: list[OrgUnit] = []
    current = db.get(OrgUnit, unit_id)
    while current is not None:
        path.append(current)
        current = db.get(OrgUnit, current.parent_id) if current.parent_id else None
    return list(reversed(path))


def unit_ref(unit: OrgUnit | None) -> dict | None:
    if unit is None:
        return None
    return {"id": unit.id, "code": unit.code, "type": unit.unit_type, "name": unit.name, "name_ar": unit.name_ar}
