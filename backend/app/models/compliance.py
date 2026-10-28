from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UTCDateTime
from app.core.ids import new_id, utcnow


class ComplianceItem(Base):
    """Undertakings, submissions and validity items. due_at (action deadline) is kept separate from
    valid_until (document/lease expiry)."""

    __tablename__ = "compliance_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("comp"))
    institution_id: Mapped[str] = mapped_column(String(64), ForeignKey("institutions.id"), index=True)
    application_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("applications.id"), nullable=True, index=True
    )
    item_type: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(300))
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    responsible_role: Mapped[str] = mapped_column(String(40))
    verified_by: Mapped[str | None] = mapped_column(String(64), ForeignKey("users.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Document(Base):
    """Metadata only; file bytes live in storage and are referenced by storage_key."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("doc"))
    institution_id: Mapped[str] = mapped_column(String(64), ForeignKey("institutions.id"), index=True)
    application_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("applications.id"), nullable=True, index=True
    )
    compliance_item_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("compliance_items.id"), nullable=True, index=True
    )
    document_type: Mapped[str] = mapped_column(String(100))
    filename: Mapped[str] = mapped_column(String(300))
    storage_key: Mapped[str] = mapped_column(String(500))
    uploaded_by: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(32), default="PENDING")


class EvcRecord(Base):
    __tablename__ = "evc_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("evc"))
    application_id: Mapped[str] = mapped_column(String(64), ForeignKey("applications.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    coordinator_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
