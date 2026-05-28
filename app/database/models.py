import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserLink(Base):
    __tablename__ = "user_links"

    user_uuid: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)

    habits: Mapped[list["UserHabit"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    memories: Mapped[list["UserVectorMemory"]] = relationship(back_populates="user", cascade="all, delete-orphan")


HABIT_TYPES = ("pre_destruction", "destruction", "stabilization")
HABIT_STATUSES = ("active", "completed", "failed")


class UserHabit(Base):
    __tablename__ = "user_habits"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_uuid: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_links.user_uuid"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(20), default="pre_destruction")
    category: Mapped[str] = mapped_column(String(100), default="custom")

    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    meta_kod: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    target_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(20), default="active")
    logs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["UserLink"] = relationship(back_populates="habits")


class UserVectorMemory(Base):
    __tablename__ = "user_vector_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_uuid: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_links.user_uuid"), nullable=False, index=True)
    embedding_vector: Mapped[Vector] = mapped_column(Vector(768), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped["UserLink"] = relationship(back_populates="memories")
