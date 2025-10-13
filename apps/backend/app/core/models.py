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
    non_functionals: list[str] = []


class AcceptanceCriteria(BaseModel):
    story_id: str
    gherkin: str


class Story(BaseModel):
    id: str
    epic_id: Optional[str] = None
    title: str
    description: str
    acceptance: list[AcceptanceCriteria] = []


class Task(BaseModel):
    id: str
    story_id: str
    title: str
    definition_of_done: list[str]


class DesignNote(BaseModel):
    id: Optional[str] = None
    scope: str
    decisions: list[str]
    interfaces: dict[str, str]


class BacklogBundle(BaseModel):
    stories: list[Story]
    tasks: list[Task]
    acceptance: list[AcceptanceCriteria]
    design: Optional[DesignNote] = None


# ====== Run / Manifest ======
class RunCreate(BaseModel):
    title: str = Field(..., description="Short label for the run")
    requirement_title: str
    requirement_description: str
    constraints: list[str] = []
    priority: Literal["Must", "Should", "Could"] = "Should"
    non_functionals: list[str] = []


class RunManifest(BaseModel):
    run_id: str
    model: str
    provider: str | None
    temperature: float
    context_snapshot_id: str