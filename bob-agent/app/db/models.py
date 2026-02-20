from datetime import datetime

from sqlalchemy import JSON, TIMESTAMP, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# JSONB on PostgreSQL, plain JSON on SQLite (for unit tests)
_JSONB = JSONB().with_variant(JSON(), "sqlite")

from app.db.database import Base


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    document_url: Mapped[str | None] = mapped_column(Text)
    sheet_name: Mapped[str | None] = mapped_column(String(255))
    training_phase: Mapped[str] = mapped_column(String(64), server_default="")
    context: Mapped[dict] = mapped_column(_JSONB, server_default="{}")
    logo_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Defect(Base):
    __tablename__ = "defects"
    __table_args__ = (UniqueConstraint("site_id", "defect_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    defect_id: Mapped[int] = mapped_column(Integer, nullable=False)
    site_id: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reporter: Mapped[str | None] = mapped_column(String(64))
    supplier: Mapped[str] = mapped_column(String(255), server_default="")
    location: Mapped[str] = mapped_column(String(255), server_default="")
    image_url: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[str] = mapped_column(String(32), server_default="פתוח")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProcessedMessage(Base):
    __tablename__ = "processed_messages"

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
