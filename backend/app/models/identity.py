from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UTCDateTime
from app.core.ids import new_id, utcnow


class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("inst"))
    name: Mapped[str] = mapped_column(String(300))
    institution_code: Mapped[str] = mapped_column(String(64), unique=True)
    region_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("usr"))
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(40), index=True)
    institution_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("institutions.id"), nullable=True, index=True
    )
    region_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
