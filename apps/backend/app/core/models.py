from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field

PromptContextMode = Literal["structured", "features_only", "minimal", "flat"]
# "flat" kept for backwards-compat with older runs; treated as "features_only" in logic.


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
    feedback_human: str | None = None
    feedback_ai: str | None = None

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
    feedback_human: str | None = None
    feedback_ai: str | None = None

class TechnicalSolution(BaseModel):
    id: str
    stack: list[str] = Field(default_factory=list)# e.g., ["node", "vite", "react", "sqlite"]
    modules: list[str] = Field(default_factory=list)
    interfaces: dict[str, str] = Field(default_factory=dict)
    decisions: list[str] = Field(default_factory=list)
    feedback_human: str | None = None
    feedback_ai: str | None = None

class Epic(BaseModel):
    id: str
    title: str
    description: str = ""
    priority_rank: int = Field(ge=1, description="1 = highest priority")
    feedback_human: str | None = None
    feedback_ai: str | None = None
    depends_on: list[str] = []

    @property
    def order_by(self) -> int:
        #alias used by planners/UI
        return self.priority_rank

class Story(BaseModel): # extend exiting Story if already defined; else define
    id: str
    epic_id: str
    title: str
    description: str = ""
    priority_rank: int = Field(ge=1, description="1 = highest priority")
    acceptance: list["AcceptanceCriteria"] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    feedback_human: str | None = None
    feedback_ai: str | None = None
    depends_on: list[str] = []

    @property
    def order_by(self) -> int:
        return self.priority_rank

class PlanBundle(BaseModel):
    product_vision: ProductVision
    technical_solution: TechnicalSolution
    epics: list[Epic] = Field(default_factory=list)
    stories: list[Story] = Field(default_factory=list)
    design_notes: list[DesignNote] = Field(default_factory=list)

# ====== Run / Manifest ======
class RunCreate(BaseModel):
    run_title: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Short description for the run",
    )
    requirement_title: str
    requirement_description: str
    constraints: list[str] = Field(default_factory=list)
    priority: Literal["Must", "Should", "Could"] = "Should"
    non_functionals: list[str] = Field(default_factory=list)

    # --- Experiment knobs (optional on input) ---
    experiment_label: Optional[str] = Field(
        default=None,
        description="Human-readable trial/ablation label; falls back to settings.EXPERIMENT_LABEL",
    )
    prompt_context_mode: PromptContextMode = "structured"
    # None means: use settings.USE_RAG as the default
    use_rag: Optional[bool] = None


class RunManifest(BaseModel):
    run_id: str
    model: str
    provider: str | None
    temperature: float
    context_snapshot_id: str

    # --- Experiment snapshot for this run ---
    # e.g. "trial1.baseline", "trial3.best", "ablation.rag_off"
    experiment_label: Optional[str] = Field(
        default=None,
        description="Human-readable experiment/trial label."
    )

    # Prompt context mode used for the RA chain
    # "structured"    = full context
    # "features_only" = features-only, best RA prompt
    # "minimal"       = features-only, minimal RA prompt
    # "flat"          = legacy alias for "features_only"
    prompt_context_mode: PromptContextMode = "structured"

    # Whether RAG retrieval was enabled for this run
    use_rag: bool = True