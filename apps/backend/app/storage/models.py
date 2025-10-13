from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Text, ForeignKey, DateTime, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.storage.db import Base


# Runs
class RunORM(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RunManifestORM(Base):
    __tablename__ = "run_manifests"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    run: Mapped[RunORM] = relationship(backref="manifest")

# Core artefacts

class RequirementORM(Base):
    __tablename__ = "requirements"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    constraints: Mapped[list] = mapped_column(JSON, default=list)
    priority: Mapped[str] = mapped_column(String(10), default="Should")
    non_functionals: Mapped[list] = mapped_column(JSON, default=list)
    run: Mapped[RunORM] = relationship(backref="requirements")


class StoryORM(Base):
    __tablename__ = "stories"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")


class TaskORM(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    definition_of_done: Mapped[list] = mapped_column(JSON, default=list)


class AcceptanceORM(Base):
    __tablename__ = "acceptance"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"))
    gherkin: Mapped[str] = mapped_column(Text)


class DesignNoteORM(Base):
    __tablename__ = "design_notes"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(50))
    decisions: Mapped[list] = mapped_column(JSON, default=list)
    interfaces: Mapped[dict] = mapped_column(JSON, default=dict)

# Logs

class RetrievalLogORM(Base):
    __tablename__ = "retrieval_logs"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    agent: Mapped[str] = mapped_column(String(50))
    query: Mapped[str] = mapped_column(Text)
    doc_ids: Mapped[list] = mapped_column(JSON, default=list)
    scores: Mapped[list] = mapped_column(JSON, default=list)
    scope: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())