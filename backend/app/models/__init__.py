"""SQLAlchemy models. Importing this package registers every table on ``Base.metadata``."""

from app.models.ai import AIGeneration
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
from app.models.config import AppSetting, DbConnection
from app.models.learning import CoachingSession, LearningGeneration, TrainingRecord
from app.models.onboarding import (
    OnboardingImport,
    OnboardingInvite,
    OnboardingProgress,
    OnboardingWave,
    PolicyAcknowledgement,
)
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
from app.models.workplace import AttendanceDay, ConductObservation, WorkplaceException

__all__ = [
    "AIGeneration",
    "AppSetting",
    "AttendanceDay",
    "ConductObservation",
    "DbConnection",
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
    "OnboardingImport",
    "OnboardingInvite",
    "OnboardingProgress",
    "OnboardingWave",
    "OrgUnit",
    "Pipeline",
    "PolicyAcknowledgement",
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
    "WorkplaceException",
]
