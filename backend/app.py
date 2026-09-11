from datetime import date, datetime, timezone
from typing import Annotated, List, Literal, Optional
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session, selectinload

from pathlib import Path

# ==========================================
# Database Configuration & Engine
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = f"sqlite:///{BASE_DIR / 'app.db'}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==========================================
# SQLAlchemy ORM Models
# ==========================================
class Priority(Base):
    __tablename__ = "priorities"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True, default="")
    owner = Column(String, nullable=False)
    target_date = Column(String, nullable=False)
    status = Column(String, nullable=False, default="On Track")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    actions = relationship("Action", back_populates="priority", cascade="all, delete-orphan")


class Action(Base):
    __tablename__ = "actions"

    id = Column(Integer, primary_key=True, index=True)
    priority_id = Column(Integer, ForeignKey("priorities.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True, default="")
    owner = Column(String, nullable=False)
    target_date = Column(String, nullable=False)
    status = Column(String, nullable=False, default="On Track")
    progress = Column(Float, default=0.0)

    priority = relationship("Priority", back_populates="actions")
    subactions = relationship("SubAction", back_populates="action", cascade="all, delete-orphan")
    reviews = relationship("Review", back_populates="action", cascade="all, delete-orphan")


class SubAction(Base):
    __tablename__ = "subactions"

    id = Column(Integer, primary_key=True, index=True)
    action_id = Column(Integer, ForeignKey("actions.id"), nullable=False)
    title = Column(String, nullable=False)
    due_date = Column(String, nullable=False)
    completed = Column(Boolean, default=False)

    action = relationship("Action", back_populates="subactions")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    action_id = Column(Integer, ForeignKey("actions.id"), nullable=False)
    reviewer_name = Column(String, nullable=False)
    date = Column(String, nullable=False)
    comment = Column(String, nullable=False)
    status = Column(String, nullable=False)  # "Approved" or "Needs Improvement"

    action = relationship("Action", back_populates="reviews")


# Create tables on startup
Base.metadata.create_all(bind=engine)


# ==========================================
# Dynamic Calculation Helpers
# ==========================================
def calculate_action_progress(action: Action) -> float:
    """Action Progress = (Completed Sub-Actions / Total Sub-Actions) * 100. Returns 0.0 if empty."""
    if not action.subactions:
        return 0.0
    total = len(action.subactions)
    completed = sum(1 for s in action.subactions if s.completed)
    return round((completed / total) * 100.0, 1)


def update_action_progress(action: Action, db: Session) -> float:
    db.flush()
    db.expire(action, ["subactions"])
    action.progress = calculate_action_progress(action)
    db.commit()
    db.refresh(action)
    return action.progress


def calculate_priority_progress(priority: Priority) -> float:
    """Priority progress equals average of linked actions' progress percentages, or 0.0."""
    if not priority.actions:
        return 0.0
    total_progress = sum(calculate_action_progress(a) for a in priority.actions)
    return round(total_progress / len(priority.actions), 1)


# ==========================================
# Pydantic v2 Schemas
# ==========================================
def validate_date(value: str) -> str:
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("Use YYYY-MM-DD for dates")
    return value


RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
DateText = Annotated[RequiredText, AfterValidator(validate_date)]
TrackingStatus = Literal["On Track", "At Risk", "Off Track"]


class SubActionCreate(BaseModel):
    title: RequiredText
    due_date: DateText


class SubActionResponse(BaseModel):
    id: int
    action_id: int
    title: str
    due_date: str
    completed: bool

    model_config = ConfigDict(from_attributes=True)


class ReviewCreate(BaseModel):
    reviewer_name: RequiredText
    date: DateText
    comment: RequiredText
    status: Literal["Approved", "Needs Improvement"]


class ReviewResponse(BaseModel):
    id: int
    action_id: int
    reviewer_name: str
    date: str
    comment: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class ActionCreate(BaseModel):
    title: RequiredText
    description: Optional[str] = ""
    owner: RequiredText
    target_date: DateText
    status: TrackingStatus = "On Track"


class ActionResponse(BaseModel):
    id: int
    priority_id: int
    title: str
    description: Optional[str] = ""
    owner: str
    target_date: str
    status: str
    progress: float

    model_config = ConfigDict(from_attributes=True)


class ActionDetailResponse(ActionResponse):
    priority_title: Optional[str] = None
    subactions: List[SubActionResponse] = []
    reviews: List[ReviewResponse] = []


class PriorityCreate(BaseModel):
    title: RequiredText
    description: Optional[str] = ""
    owner: RequiredText
    target_date: DateText
    status: TrackingStatus = "On Track"


class PriorityResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = ""
    owner: str
    target_date: str
    status: str
    created_at: Optional[datetime] = None
    progress: float
    actions_count: int

    model_config = ConfigDict(from_attributes=True)


class PriorityDetailResponse(PriorityResponse):
    actions: List[ActionResponse] = []


class DashboardStatsResponse(BaseModel):
    overall_progress: float
    priorities_count: int
    actions_count: int
    completed_count: int
    on_track_count: int
    at_risk_count: int
    off_track_count: int


# ==========================================
# FastAPI Application & Endpoints
# ==========================================
app = FastAPI(
    title="Priority & Action Tracking API",
    description="Mobile-first strategic priority and action tracker backend",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/dashboard/stats", response_model=DashboardStatsResponse)
def get_dashboard_stats(db: Session = Depends(get_db)):
    priorities = db.query(Priority).options(selectinload(Priority.actions).selectinload(Action.subactions)).all()
    actions = [action for priority in priorities for action in priority.actions]

    priorities_count = len(priorities)
    actions_count = len(actions)

    # Dynamic Overall Progress = Average across all priorities
    if priorities:
        priority_progresses = [calculate_priority_progress(p) for p in priorities]
        overall_progress = round(sum(priority_progresses) / len(priorities), 1)
    else:
        overall_progress = 0.0

    completed_count = sum(1 for a in actions if calculate_action_progress(a) >= 100.0)

    # Status counts: based on actions if actions exist, otherwise priorities
    if actions:
        on_track_count = sum(1 for a in actions if a.status == "On Track")
        at_risk_count = sum(1 for a in actions if a.status == "At Risk")
        off_track_count = sum(1 for a in actions if a.status == "Off Track")
    else:
        on_track_count = sum(1 for p in priorities if p.status == "On Track")
        at_risk_count = sum(1 for p in priorities if p.status == "At Risk")
        off_track_count = sum(1 for p in priorities if p.status == "Off Track")

    return DashboardStatsResponse(
        overall_progress=overall_progress,
        priorities_count=priorities_count,
        actions_count=actions_count,
        completed_count=completed_count,
        on_track_count=on_track_count,
        at_risk_count=at_risk_count,
        off_track_count=off_track_count
    )


@app.get("/api/priorities", response_model=List[PriorityResponse])
def get_priorities(db: Session = Depends(get_db)):
    priorities = db.query(Priority).options(selectinload(Priority.actions).selectinload(Action.subactions)).order_by(Priority.created_at.desc()).all()
    results = []
    for p in priorities:
        results.append(
            PriorityResponse(
                id=p.id,
                title=p.title,
                description=p.description or "",
                owner=p.owner,
                target_date=p.target_date,
                status=p.status,
                created_at=p.created_at,
                progress=calculate_priority_progress(p),
                actions_count=len(p.actions)
            )
        )
    return results


@app.post("/api/priorities", response_model=PriorityResponse, status_code=status.HTTP_201_CREATED)
def create_priority(payload: PriorityCreate, db: Session = Depends(get_db)):
    priority = Priority(
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else "",
        owner=payload.owner.strip(),
        target_date=payload.target_date.strip(),
        status=payload.status or "On Track"
    )
    db.add(priority)
    db.commit()
    db.refresh(priority)
    return PriorityResponse(
        id=priority.id,
        title=priority.title,
        description=priority.description or "",
        owner=priority.owner,
        target_date=priority.target_date,
        status=priority.status,
        created_at=priority.created_at,
        progress=0.0,
        actions_count=0
    )


@app.get("/api/priorities/{priority_id}", response_model=PriorityDetailResponse)
def get_priority_detail(priority_id: int, db: Session = Depends(get_db)):
    priority = db.query(Priority).options(selectinload(Priority.actions).selectinload(Action.subactions)).filter(Priority.id == priority_id).first()
    if not priority:
        raise HTTPException(status_code=404, detail="Priority not found")

    actions_response = [
        ActionResponse.model_validate(action).model_copy(update={"progress": calculate_action_progress(action)}) for action in priority.actions
    ]

    return PriorityDetailResponse(
        id=priority.id,
        title=priority.title,
        description=priority.description or "",
        owner=priority.owner,
        target_date=priority.target_date,
        status=priority.status,
        created_at=priority.created_at,
        progress=calculate_priority_progress(priority),
        actions_count=len(priority.actions),
        actions=actions_response
    )


@app.get("/api/priorities/{priority_id}/actions", response_model=List[ActionResponse])
def get_priority_actions(priority_id: int, db: Session = Depends(get_db)):
    priority = db.query(Priority).options(selectinload(Priority.actions).selectinload(Action.subactions)).filter(Priority.id == priority_id).first()
    if not priority:
        raise HTTPException(status_code=404, detail="Priority not found")
    return [ActionResponse.model_validate(action).model_copy(update={"progress": calculate_action_progress(action)}) for action in priority.actions]


@app.post("/api/priorities/{priority_id}/actions", response_model=ActionResponse, status_code=status.HTTP_201_CREATED)
def create_priority_action(priority_id: int, payload: ActionCreate, db: Session = Depends(get_db)):
    priority = db.query(Priority).filter(Priority.id == priority_id).first()
    if not priority:
        raise HTTPException(status_code=404, detail="Priority not found")

    action = Action(
        priority_id=priority_id,
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else "",
        owner=payload.owner.strip(),
        target_date=payload.target_date.strip(),
        status=payload.status or "On Track",
        progress=0.0
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return ActionResponse.model_validate(action)


@app.get("/api/actions", response_model=List[ActionResponse])
def get_all_actions(db: Session = Depends(get_db)):
    actions = db.query(Action).options(selectinload(Action.subactions)).all()
    return [ActionResponse.model_validate(a).model_copy(update={"progress": calculate_action_progress(a)}) for a in actions]


@app.get("/api/actions/{action_id}", response_model=ActionDetailResponse)
def get_action_detail(action_id: int, db: Session = Depends(get_db)):
    action = db.query(Action).filter(Action.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    # Refresh progress based on current subactions
    progress = calculate_action_progress(action)

    subactions = [SubActionResponse.model_validate(s) for s in action.subactions]
    reviews = [ReviewResponse.model_validate(r) for r in action.reviews]

    return ActionDetailResponse(
        id=action.id,
        priority_id=action.priority_id,
        priority_title=action.priority.title if action.priority else None,
        title=action.title,
        description=action.description or "",
        owner=action.owner,
        target_date=action.target_date,
        status=action.status,
        progress=progress,
        subactions=subactions,
        reviews=reviews
    )


@app.post("/api/actions/{action_id}/subactions", response_model=SubActionResponse, status_code=status.HTTP_201_CREATED)
def create_subaction(action_id: int, payload: SubActionCreate, db: Session = Depends(get_db)):
    action = db.query(Action).filter(Action.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    subaction = SubAction(
        action_id=action_id,
        title=payload.title.strip(),
        due_date=payload.due_date.strip(),
        completed=False
    )
    db.add(subaction)
    # Save the subaction and parent progress in one transaction.
    update_action_progress(action, db)
    return SubActionResponse.model_validate(subaction)


@app.patch("/api/subactions/{subaction_id}/toggle")
def toggle_subaction(subaction_id: int, db: Session = Depends(get_db)):
    subaction = db.query(SubAction).filter(SubAction.id == subaction_id).first()
    if not subaction:
        raise HTTPException(status_code=404, detail="SubAction not found")

    subaction.completed = not subaction.completed
    # Trigger recalculation of parent action progress
    action = subaction.action
    new_progress = update_action_progress(action, db)

    return {
        "subaction": SubActionResponse.model_validate(subaction),
        "action_progress": new_progress
    }


@app.post("/api/actions/{action_id}/reviews", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
def create_review(action_id: int, payload: ReviewCreate, db: Session = Depends(get_db)):
    action = db.query(Action).filter(Action.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    review = Review(
        action_id=action_id,
        reviewer_name=payload.reviewer_name.strip(),
        date=payload.date.strip(),
        comment=payload.comment.strip(),
        status=payload.status.strip()
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return ReviewResponse.model_validate(review)


@app.delete("/api/priorities/{priority_id}")
def delete_priority(priority_id: int, db: Session = Depends(get_db)):
    priority = db.query(Priority).filter(Priority.id == priority_id).first()
    if not priority:
        raise HTTPException(status_code=404, detail="Priority not found")
    db.delete(priority)
    db.commit()
    return {"message": "Priority deleted successfully"}


@app.delete("/api/actions/{action_id}")
def delete_action(action_id: int, db: Session = Depends(get_db)):
    action = db.query(Action).filter(Action.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    db.delete(action)
    db.commit()
    return {"message": "Action deleted successfully"}


@app.delete("/api/subactions/{subaction_id}")
def delete_subaction(subaction_id: int, db: Session = Depends(get_db)):
    subaction = db.query(SubAction).filter(SubAction.id == subaction_id).first()
    if not subaction:
        raise HTTPException(status_code=404, detail="SubAction not found")
    action = subaction.action
    db.delete(subaction)
    update_action_progress(action, db)
    return {"message": "SubAction deleted successfully"}
