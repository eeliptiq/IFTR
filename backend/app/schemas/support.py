"""
Request/response models for the community support board.

The board is one thing with two faces: `Support.js` reads it as questions and
answers, and `DriverRouting.js` reads the same rows filtered to `routing` and
calls the answers "confirmations". Both use the same shapes, so the route-tip
screen does not need a parallel API.

`is_mine` is computed per request from the caller's id, instead of exposing
everybody's `user_id` so the page can compare them. The frontend only needs to
know whether to offer the accept button, and that is a fact about the viewer,
not about the question.
"""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.support_orm import SupportAnswerRecord, SupportQuestionRecord
from app.schemas._time import as_utc

# The categories the board offers. `routing` is not in the Support page's filter
# row but the driver route-tips screen posts and reads it, so it is part of the
# vocabulary. Anything else is refused rather than filed under "general", which
# would make the filter lie.
SupportCategory = Literal[
    "general",
    "delivery",
    "payment",
    "restaurant",
    "technical",
    "routing",
]


class SupportQuestionCreate(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    category: SupportCategory = "general"

    @field_validator("question")
    @classmethod
    def _not_only_whitespace(cls, value: str) -> str:
        # A single space passes `min_length`; it would post an empty card.
        stripped = value.strip()
        if not stripped:
            raise ValueError("question cannot be blank")
        return stripped


class SupportAnswerCreate(BaseModel):
    question_id: str = Field(min_length=1, max_length=64)
    answer: str = Field(min_length=1, max_length=2000)

    @field_validator("answer")
    @classmethod
    def _not_only_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("answer cannot be blank")
        return stripped


class SupportAnswerResponse(BaseModel):
    answer_id: str
    question_id: str
    user_name: str = ""
    user_role: str = "customer"
    answer: str
    is_accepted: bool = False
    upvotes: int = 0
    created_at: datetime

    @classmethod
    def from_record(cls, record: SupportAnswerRecord) -> "SupportAnswerResponse":
        return cls(
            answer_id=record.answer_id,
            question_id=record.question_id,
            user_name=record.user_name or "",
            user_role=record.user_role or "customer",
            answer=record.answer,
            is_accepted=bool(record.is_accepted),
            upvotes=record.upvotes or 0,
            created_at=as_utc(record.created_at),
        )


class SupportQuestionResponse(BaseModel):
    question_id: str
    user_name: str = ""
    user_role: str = "customer"
    question: str
    category: str = "general"
    is_resolved: bool = False
    created_at: datetime
    answers: List[SupportAnswerResponse] = Field(default_factory=list)
    # True when the caller wrote this question, i.e. may accept an answer.
    is_mine: bool = False

    @classmethod
    def from_records(
        cls,
        record: SupportQuestionRecord,
        answers: Optional[List[SupportAnswerRecord]] = None,
        viewer_id: str = "",
    ) -> "SupportQuestionResponse":
        return cls(
            question_id=record.question_id,
            user_name=record.user_name or "",
            user_role=record.user_role or "customer",
            question=record.question,
            category=record.category or "general",
            is_resolved=bool(record.is_resolved),
            created_at=as_utc(record.created_at),
            answers=[
                SupportAnswerResponse.from_record(answer) for answer in (answers or [])
            ],
            is_mine=bool(viewer_id) and record.user_id == viewer_id,
        )
