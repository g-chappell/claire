from __future__ import annotations
from typing import List, Dict
from pydantic import BaseModel, Field, field_validator

# Worker outputs (drafts). We'll convert to final domain models in the PM orchestrator.

class ProductVisionDraft(BaseModel):
    goals: List[str] = Field(default_factory=list)
    personas: List[str] = Field(default_factory=list)
    features: List[str] = Field(default_factory=list)

class TechnicalSolutionDraft(BaseModel):
    stack: List[str] = Field(default_factory=list)         # e.g., ["node","vite","react","sqlite"]
    modules: List[str] = Field(default_factory=list)
    interfaces: Dict[str, str] = Field(default_factory=dict)
    decisions: List[str] = Field(default_factory=list)

class EpicDraft(BaseModel):
    title: str
    description: str = ""

class StoryDraft(BaseModel):
    epic_title: str               # map to epic_id later
    title: str
    description: str = ""

class RAPlanDraft(BaseModel):
    epics: List[EpicDraft] = Field(default_factory=list)
    stories: List[StoryDraft] = Field(default_factory=list)

class QASpec(BaseModel):
    gherkin: List[str] = Field(default_factory=list)
    unit_tests: List[str] = Field(default_factory=list)

    @field_validator("gherkin", "unit_tests", mode="before")
    @classmethod
    def _coerce_list(cls, v):
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            # Best-effort: if model returned a big block, just wrap it
            # (we can get fancier later by splitting on Scenario:/bullets)
            return [s]
        # Fallback: try list(...) safely
        try:
            return [str(x).strip() for x in list(v) if str(x).strip()]
        except Exception:
            return [str(v)]
