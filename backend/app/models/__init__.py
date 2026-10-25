"""SQLAlchemy models. Importing this package registers every table on ``Base.metadata``."""

from app.models.cases import (
    EmployeeResponse,
    EvidenceRef,
    Finding,
    FollowUpEvaluation,
    ImprovementAction,
    MistakeRule,
    PolicyVersion,
    ReviewDecision,
    ServiceCase,
    SourceSystem,
)
from app.models.learning import CoachingSession, LearningGeneration, TrainingRecord
from app.models.ops import (
    AuditEvent,
    IngestionRun,
    ModelRegistry,
    ModelRun,
    Pipeline,
    QuarantinedRecord,
    ServiceHeartbeat,
    SimulationRun,
)
from app.models.org import AuthSession, EmployeeProfile, OrgUnit, Role, User, UserRole

__all__ = [
    "AuditEvent",
    "AuthSession",
    "CoachingSession",
    "EmployeeProfile",
    "EmployeeResponse",
    "EvidenceRef",
    "Finding",
    "FollowUpEvaluation",
    "ImprovementAction",
    "IngestionRun",
    "LearningGeneration",
    "MistakeRule",
    "ModelRegistry",
    "ModelRun",
    "OrgUnit",
    "Pipeline",
    "PolicyVersion",
    "QuarantinedRecord",
    "ReviewDecision",
    "Role",
    "ServiceCase",
    "ServiceHeartbeat",
    "SimulationRun",
    "SourceSystem",
    "TrainingRecord",
    "User",
    "UserRole",
]
