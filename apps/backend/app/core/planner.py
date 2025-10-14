from __future__ import annotations
import uuid
from sqlalchemy.orm import Session

from app.core.models import PlanBundle, ProductVision, TechnicalSolution, Epic, Story, AcceptanceCriteria
from app.storage.models import (
    RequirementORM, ProductVisionORM, TechnicalSolutionORM,
    EpicORM, StoryORM, AcceptanceORM
)
from app.agents.meta.product_manager_llm import ProductManagerLLM

pm = ProductManagerLLM()

def _persist_plan(db: Session, run_id: str, requirement: RequirementORM, bundle: PlanBundle) -> None:
    # product vision & technical solution as JSON blobs
    db.merge(ProductVisionORM(run_id=run_id, data=bundle.product_vision.model_dump()))
    db.merge(TechnicalSolutionORM(run_id=run_id, data=bundle.technical_solution.model_dump()))

    # epics
    for e in bundle.epics:
        db.merge(EpicORM(
            id=e.id, run_id=run_id, title=e.title,
            description=e.description, priority_rank=e.priority_rank
        ))

    # stories + acceptance
    for s in bundle.stories:
        db.merge(StoryORM(
            id=s.id, run_id=run_id, requirement_id=requirement.id,
            epic_id=s.epic_id, title=s.title, description=s.description,
            priority_rank=s.priority_rank, tests=s.tests
        ))
        # clear+write acceptance entries (simple approach: upsert by id)
        for i, ac in enumerate(s.acceptance, start=1):
            db.merge(AcceptanceORM(
                id=f"AC-{s.id}-{i}", run_id=run_id, story_id=s.id, gherkin=ac.gherkin
            ))

    db.commit()

def plan_run(db: Session, run_id: str) -> PlanBundle:
    req: RequirementORM | None = (
        db.query(RequirementORM)
        .filter(RequirementORM.run_id == run_id)
        .order_by(RequirementORM.id.asc())
        .first()
    )
    if not req:
        raise ValueError("requirement not found for run")

    p_req = Requirement(
        id=req.id, title=req.title, description=req.description,
        constraints=req.constraints or [], priority=req.priority or "Should",
        non_functionals=req.non_functionals or [],
    )

    bundle = pm.plan(p_req.model_dump())
    _persist_plan(db, run_id, req, bundle)
    return bundle

def read_plan(db: Session, run_id: str) -> PlanBundle:
    pv = db.query(ProductVisionORM).filter_by(run_id=run_id).first()
    ts = db.query(TechnicalSolutionORM).filter_by(run_id=run_id).first()
    if not pv or not ts:
        raise ValueError("plan not found for run")

    epics_orm = db.query(EpicORM).filter_by(run_id=run_id).order_by(EpicORM.priority_rank.asc()).all()
    stories_orm = db.query(StoryORM).filter_by(run_id=run_id).order_by(StoryORM.epic_id, StoryORM.priority_rank.asc()).all()

    # map acceptance by story
    ac_rows = db.query(AcceptanceORM).filter_by(run_id=run_id).all()
    ac_by_story = {}
    for r in ac_rows:
        ac_by_story.setdefault(r.story_id, []).append(AcceptanceCriteria(story_id=r.story_id, gherkin=r.gherkin))

    epics = [Epic(id=e.id, title=e.title, description=e.description, priority_rank=e.priority_rank) for e in epics_orm]
    stories = [
        Story(
            id=s.id, epic_id=s.epic_id, title=s.title, description=s.description,
            priority_rank=s.priority_rank or 1, acceptance=ac_by_story.get(s.id, []), tests=s.tests or []
        )
        for s in stories_orm
    ]

    return PlanBundle(
        product_vision=ProductVision(**pv.data),
        technical_solution=TechnicalSolution(**ts.data),
        epics=epics,
        stories=stories,
    )
