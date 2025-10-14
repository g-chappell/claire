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

class ProductVision(BaseModel):
    id: str
    goals: list[str]
    personas: list[str] = []
    features: list[str]

class TechnicalSolution(BaseModel):
    id: str
    stack: list[str] # e.g., ["node", "vite", "react", "sqlite"]
    modules: list[str]
    interfaces: dict[str, str]
    decisions: list[str]


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
    acceptance: list["AcceptanceCriteria"] = [] # forward ref ok
    tests: list[str] = []

class PlanBundle(BaseModel):
    product_vision: ProductVision
    technical_solution: TechnicalSolution
    epics: list[Epic]
    stories: list[Story]

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