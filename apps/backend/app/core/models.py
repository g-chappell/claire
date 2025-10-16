from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


# ====== Domain ======
class Requirement(BaseModel):
    id: str
    title: str
    description: str
    constraints: list[str] = []
    priority: Literal["Must", "Should", "Could"] = "Should"
    non_functionals: list[str] = Field(default_factory=list)


class AcceptanceCriteria(BaseModel):
    story_id: str
    gherkin: str

class Task(BaseModel):
    id: str
    story_id: str
    title: str
    order: int = 1
    status: Literal["todo", "doing", "done"] = "todo"  # optional; will be filtered if ORM lacks this column


class DesignNote(BaseModel):
    id: str
    title: str
    kind: Literal["overview", "api", "frontend", "repo", "quality", "risk", "other"]  # overview|api|frontend|repo|quality|risk|other
    body_md: str
    tags: list[str] = Field(default_factory=list)
    related_epic_ids: list[str] = Field(default_factory=list)
    related_story_ids: list[str] = Field(default_factory=list)


class ProductVision(BaseModel):
    id: str
    goals: list[str] = Field(default_factory=list)
    personas: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)

class TechnicalSolution(BaseModel):
    id: str
    stack: list[str] = Field(default_factory=list)# e.g., ["node", "vite", "react", "sqlite"]
    modules: list[str] = Field(default_factory=list)
    interfaces: dict[str, str] = Field(default_factory=dict)
    decisions: list[str] = Field(default_factory=list)


class Epic(BaseModel):
    id: str
    title: str
    description: str = ""
    priority_rank: int = Field(ge=1, description="1 = highest priority")

class Story(BaseModel): # extend exiting Story if already defined; else define
    id: str
    epic_id: str
    title: str
    description: str = ""
    priority_rank: int = Field(ge=1, description="1 = highest priority")
    acceptance: list["AcceptanceCriteria"] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)

class PlanBundle(BaseModel):
    product_vision: ProductVision
    technical_solution: TechnicalSolution
    epics: list[Epic] = Field(default_factory=list)
    stories: list[Story] = Field(default_factory=list)
    design_notes: list[DesignNote] = Field(default_factory=list)

# ====== Run / Manifest ======
class RunCreate(BaseModel):
    run_title: Optional[str] = Field(default=None, max_length=200, description="Short description for the run")
    requirement_title: str
    requirement_description: str
    constraints: list[str] = Field(default_factory=list)
    priority: Literal["Must", "Should", "Could"] = "Should"
    non_functionals: list[str] = Field(default_factory=list)


class RunManifest(BaseModel):
    run_id: str
    model: str
    provider: str | None
    temperature: float
    context_snapshot_id: str