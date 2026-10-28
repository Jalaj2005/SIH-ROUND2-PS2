"""Import every model so Base.metadata knows all tables."""
from app.models.compliance import ComplianceItem, Document, EvcRecord
from app.models.identity import Institution, User
from app.models.ops import AuditLog, Escalation, Notification, WorkflowRule
from app.models.workflow import (
    Application,
    ApplicationStageHistory,
    WorkflowStage,
    WorkflowTemplate,
    WorkflowTransition,
)

__all__ = [
    "Application",
    "ApplicationStageHistory",
    "AuditLog",
    "ComplianceItem",
    "Document",
    "Escalation",
    "EvcRecord",
    "Institution",
    "Notification",
    "User",
    "WorkflowRule",
    "WorkflowStage",
    "WorkflowTemplate",
    "WorkflowTransition",
]
