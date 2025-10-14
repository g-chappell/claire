from __future__ import annotations
from typing import List, Dict, Literal
from pydantic import BaseModel, Field, field_validator, ConfigDict
import json

MAX_NOTES, MAX_TASKS_PER_STORY = 8, 10

STACK_MAP = {"node.js":"node", "nodejs":"node", "reactjs":"react", "sqlite3":"sqlite"}

def _strip(s: str) -> str:
    return s.strip() if isinstance(s, str) else s

class LLMModel(BaseModel):
    model_config = ConfigDict(extra="ignore")  # drop unknown keys silently

# Worker outputs (drafts). We'll convert to final domain models in the PM orchestrator.

class ProductVisionDraft(LLMModel):
    goals: List[str] = Field(default_factory=list)
    personas: List[str] = Field(default_factory=list)
    features: List[str] = Field(default_factory=list)

class TechnicalSolutionDraft(LLMModel):
    stack: List[str] = Field(default_factory=list)
    modules: List[str] = Field(default_factory=list)
    interfaces: Dict[str, str] = Field(default_factory=dict)
    decisions: List[str] = Field(default_factory=list)
    @field_validator("stack", "modules", "decisions")
    @classmethod
    def _trim_list(cls, v):
        if not isinstance(v, list): return []
        return [str(x).strip() for x in v if str(x).strip()]
    @field_validator("stack")
    @classmethod
    def _norm_stack(cls, v):
        cleaned = []
        for x in v:
            k = str(x).strip().lower()
            # keep only token before common separators
            for sep in (" - ", "—", ":", "|", "("):
                if sep in k:
                    k = k.split(sep, 1)[0].strip()
                    break
            cleaned.append(STACK_MAP.get(k, k))
        return cleaned
    @field_validator("interfaces", mode="before")
    @classmethod
    def _coerce_interfaces(cls, v):
        # dict as-is
        if isinstance(v, dict):
            return {str(k).strip(): str(val).strip() for k, val in v.items()}

        # try parse JSON string
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("{") and s.endswith("}"):
                try:
                    obj = json.loads(s)
                    if isinstance(obj, dict):
                        return {str(k).strip(): str(val).strip() for k, val in obj.items()}
                except Exception:
                    pass
            # "K:V" or "K:V\nK2:V2" fallback
            out = {}
            lines = [x for x in s.splitlines() if x.strip()]
            for line in lines:
                if ":" in line:
                    k, val = line.split(":", 1)
                    out[k.strip()] = val.strip()
            return out

        # list of "K:V"
        if isinstance(v, list):
            out = {}
            for item in v:
                s = str(item)
                if ":" in s:
                    k, val = s.split(":", 1)
                    out[k.strip()] = val.strip()
            return out

        return {}

class EpicDraft(LLMModel):
    title: str
    description: str = ""
    @field_validator("title", "description")
    @classmethod
    def _trim(cls, v): return _strip(v)

class StoryDraft(LLMModel):
    epic_title: str
    title: str
    description: str = ""
    @field_validator("epic_title", "title", "description")
    @classmethod
    def _trim(cls, v): return _strip(v)

class RAPlanDraft(LLMModel):
    epics: List[EpicDraft] = Field(default_factory=list)
    stories: List[StoryDraft] = Field(default_factory=list)

class QASpec(LLMModel):
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

class DesignNoteDraft(LLMModel):
    title: str
    kind: Literal["overview","api","frontend","repo","quality","risk","other"]
    body_md: str
    tags: List[str] = Field(default_factory=list)
    related_epic_titles: List[str] = Field(default_factory=list)
    related_story_titles: List[str] = Field(default_factory=list)
    @field_validator("tags", "related_epic_titles", "related_story_titles")
    @classmethod
    def _clean_list(cls, v: List[str]) -> List[str]:
        seen, out = set(), []
        for x in v or []:
            k = x.strip()
            if not k or k.lower() in seen: 
                continue
            seen.add(k.lower())
            out.append(k)
        return out

class TaskDraft(LLMModel):
    story_title: str
    items: List[str] = Field(default_factory=list)

    @field_validator("items", mode="before")
    @classmethod
    def _coerce_items(cls, v):
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            parts = [p.strip(" -*\n\r\t") for p in v.split("\n") if p.strip()]
            return parts or [v.strip()]
        return [str(v).strip()]

    @field_validator("items")
    @classmethod
    def _cap_items(cls, v):
        return (v or [])[:MAX_TASKS_PER_STORY]

class TechWritingBundleDraft(LLMModel):
    notes: List[DesignNoteDraft] = Field(default_factory=list)
    tasks: List[TaskDraft] = Field(default_factory=list)

    @field_validator("notes", "tasks", mode="before")
    @classmethod
    def _ensure_list(cls, v):
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return [v]  # coerce single object → list

    @field_validator("notes")
    @classmethod
    def _cap_notes(cls, v):
        return (v or [])[:MAX_NOTES]
