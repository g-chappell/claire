from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Text, ForeignKey, DateTime, JSON, Integer, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.storage.db import Base


# Runs
class RunORM(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
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

class TaskORM(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    story_id: Mapped[str] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    definition_of_done: Mapped[list] = mapped_column(JSON, default=list)
    feedback_human: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_ai: Mapped[str | None] = mapped_column(Text, nullable=True)


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

# 2.1 Product Vision (1 per run)
class ProductVisionORM(Base):
    __tablename__ = "product_visions"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON) # full document


# 2.2 Technical Solution (1 per run)
class TechnicalSolutionORM(Base):
    __tablename__ = "technical_solutions"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON) # full document


# 2.3 Epics (many per run)
class EpicORM(Base):
    __tablename__ = "epics"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    # ensure deterministic ordering exists even for legacy rows
    priority_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # allow cross-epic dependencies (ids of other epics)
    depends_on: Mapped[list[str]] = mapped_column(JSON, default=list)
    feedback_human: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_ai: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_epics_run_rank", "run_id", "priority_rank"),
    )

# 2.4 Stories (extend to link epics + priority + tests)
# If StoryORM already exists, extend it by adding columns epic_id, priority_rank, tests.
class StoryORM(Base):
    __tablename__ = "stories"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"))
    epic_id: Mapped[str] = mapped_column(ForeignKey("epics.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    # deterministic ordering within each epic
    priority_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # story-to-story dependencies (ids of stories)
    depends_on: Mapped[list[str]] = mapped_column(JSON, default=list)
    tests: Mapped[list] = mapped_column(JSON, default=list)
    feedback_human: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_ai: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_stories_run_epic_rank", "run_id", "epic_id", "priority_rank"),
    )
    # relationships (optional)
    # epic: Mapped[EpicORM] = relationship(backref="stories")