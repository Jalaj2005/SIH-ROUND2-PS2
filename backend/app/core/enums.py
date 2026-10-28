"""Shared constants. Frozen at Module 0: changing a value requires an integrator decision
and an update to docs/api-contract.md. Workflow labels are prototype examples, not official AICTE labels."""
from enum import Enum

# Python 3.10 compatible StrEnum
class StrEnum(str, Enum):
    def __str__(self):
        return str(self.value)


class Role(StrEnum):
    INSTITUTION_USER = "INSTITUTION_USER"
    SCRUTINY_OFFICER = "SCRUTINY_OFFICER"
    REGIONAL_OFFICER = "REGIONAL_OFFICER"
    EVC_COORDINATOR = "EVC_COORDINATOR"
    COMMITTEE_AUTHORITY = "COMMITTEE_AUTHORITY"
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    SENIOR_MANAGEMENT = "SENIOR_MANAGEMENT"


class ScopeType(StrEnum):
    INSTITUTION = "INSTITUTION"  # exactly one institution
    REGION = "REGION"            # institutions in the user's region
    ALL = "ALL"                  # no institution/region restriction
    NONE = "NONE"                # fail closed


class ApplicationStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_SCRUTINY = "IN_SCRUTINY"
    RETURNED_FOR_DEFICIENCY = "RETURNED_FOR_DEFICIENCY"
    RESUBMITTED = "RESUBMITTED"
    RE_SCRUTINY = "RE_SCRUTINY"
    EVC_PENDING = "EVC_PENDING"
    EVC_SCHEDULED = "EVC_SCHEDULED"
    EVC_COMPLETED = "EVC_COMPLETED"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    AWAITING_AUTHORITY_DECISION = "AWAITING_AUTHORITY_DECISION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PriorityBand(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ComplianceItemType(StrEnum):
    UNDERTAKING = "UNDERTAKING"
    EVIDENCE_SUBMISSION = "EVIDENCE_SUBMISSION"
    DOCUMENT_VALIDITY = "DOCUMENT_VALIDITY"


class ComplianceStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class DeadlineState(StrEnum):
    """Derived by the deadline engine (Module 3); not stored on compliance_items."""
    UPCOMING = "UPCOMING"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    EXPIRED = "EXPIRED"


class VerificationStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class EvcStatus(StrEnum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class NotificationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    READ = "READ"
    RESOLVED = "RESOLVED"


class EscalationStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"