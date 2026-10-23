"""
Community support board: questions, answers, votes and acceptance.

Mounted under /api (see app/main.py). The same rows serve two screens: the
support page, and the driver's route-tips page, which files its tips under the
`routing` category and treats answers as confirmations.

The rules that matter:

  * Every route needs a signed-in caller. Reading the board is not secret, but
    the app has no anonymous surface and a name is attached to every post.
  * One person, one vote per answer. The prototype incremented a counter, so a
    single account could vote the same answer up repeatedly; here a vote is a
    row in `support_answer_votes`, keyed by (answer, person), and the counter
    only moves when that row is new. A repeated tap is therefore a no-op, not
    an inflation.
  * Only the person who asked may accept an answer, and accepting is what
    resolves the question. Accepting a different answer moves the mark: a
    question carries at most one accepted answer, because "resolved" with two
    contradictory accepted answers helps nobody.
  * An accepted answer sorts above upvoted ones, so the answer the asker chose
    is the first one a reader sees.
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.database import get_db
from app.models.support_orm import (
    SupportAnswerRecord,
    SupportAnswerVoteRecord,
    SupportQuestionRecord,
)
from app.models.user_orm import UserRecord
from app.schemas.support import (
    SupportAnswerCreate,
    SupportAnswerResponse,
    SupportCategory,
    SupportQuestionCreate,
    SupportQuestionResponse,
)

router = APIRouter(prefix="/support", tags=["support"])

# Enough to fill a screen; the board is browsed, not exported. Answers are
# capped too, because one heated thread should not push every other question
# off the page. The accepted answer sorts first, so the cap never hides it.
QUESTION_PAGE_SIZE = 50
MAX_ANSWERS_SHOWN = 10


async def _get_question(db: AsyncSession, question_id: str) -> SupportQuestionRecord:
    result = await db.execute(
        select(SupportQuestionRecord).where(
            SupportQuestionRecord.question_id == question_id
        )
    )
    question = result.scalar_one_or_none()
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found",
        )
    return question


async def _get_answer(db: AsyncSession, answer_id: str) -> SupportAnswerRecord:
    result = await db.execute(
        select(SupportAnswerRecord).where(SupportAnswerRecord.answer_id == answer_id)
    )
    answer = result.scalar_one_or_none()
    if answer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Answer not found",
        )
    return answer


def _accepted_first():
    """Sort key: accepted answers, then the most upvoted, then the oldest."""
    return case((SupportAnswerRecord.is_accepted.is_(True), 0), else_=1)


@router.get("/questions", response_model=List[SupportQuestionResponse])
async def list_questions(
    category: Optional[SupportCategory] = None,
    resolved: Optional[bool] = None,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    The board, newest question first.

    `category=routing` is what the route-tips screen asks for; `resolved=false`
    is the "still open" view. Answers are fetched in one query for the whole
    page rather than one per question.
    """
    query = select(SupportQuestionRecord)
    if category is not None:
        query = query.where(SupportQuestionRecord.category == category)
    if resolved is not None:
        query = query.where(SupportQuestionRecord.is_resolved.is_(resolved))

    result = await db.execute(
        query.order_by(SupportQuestionRecord.created_at.desc()).limit(
            QUESTION_PAGE_SIZE
        )
    )
    questions = result.scalars().all()
    if not questions:
        return []

    answers_by_question: Dict[str, List[SupportAnswerRecord]] = {
        question.question_id: [] for question in questions
    }
    answers = await db.execute(
        select(SupportAnswerRecord)
        .where(
            SupportAnswerRecord.question_id.in_(list(answers_by_question.keys()))
        )
        .order_by(
            SupportAnswerRecord.question_id,
            _accepted_first(),
            SupportAnswerRecord.upvotes.desc(),
            SupportAnswerRecord.created_at.asc(),
        )
    )
    for answer in answers.scalars().all():
        bucket = answers_by_question[answer.question_id]
        if len(bucket) < MAX_ANSWERS_SHOWN:
            bucket.append(answer)

    return [
        SupportQuestionResponse.from_records(
            question,
            answers_by_question[question.question_id],
            viewer_id=current_user.user_id,
        )
        for question in questions
    ]


@router.post(
    "/questions",
    response_model=SupportQuestionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ask_question(
    body: SupportQuestionCreate,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Post a question (or, from the driver screen, a route tip)."""
    question = SupportQuestionRecord(
        user_id=current_user.user_id,
        # A snapshot: the board should still say who asked if the account is
        # renamed later.
        user_name=current_user.name or "",
        user_role=current_user.role or "customer",
        question=body.question,
        category=body.category,
    )
    db.add(question)
    await db.flush()
    return SupportQuestionResponse.from_records(
        question, [], viewer_id=current_user.user_id
    )


@router.post(
    "/answers",
    response_model=SupportAnswerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def answer_question(
    body: SupportAnswerCreate,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add an answer. The question has to exist; the answer may be your own."""
    await _get_question(db, body.question_id)

    answer = SupportAnswerRecord(
        question_id=body.question_id,
        user_id=current_user.user_id,
        user_name=current_user.name or "",
        user_role=current_user.role or "customer",
        answer=body.answer,
    )
    db.add(answer)
    await db.flush()
    return SupportAnswerResponse.from_record(answer)


@router.post("/answers/{answer_id}/upvote", response_model=SupportAnswerResponse)
async def upvote_answer(
    answer_id: str,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Agree with an answer, once.

    The vote row is the record and the counter follows it, so a retried tap
    answers 200 with the same count instead of adding another vote. The
    composite primary key settles two simultaneous taps from the same person:
    one insert wins, the loser rolls back and reports the count that won.
    """
    answer = await _get_answer(db, answer_id)

    existing = await db.execute(
        select(SupportAnswerVoteRecord).where(
            SupportAnswerVoteRecord.answer_id == answer_id,
            SupportAnswerVoteRecord.user_id == current_user.user_id,
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(
            SupportAnswerVoteRecord(
                answer_id=answer_id, user_id=current_user.user_id
            )
        )
        try:
            await db.flush()
        except IntegrityError:
            # Somebody else's tap from this account got there first.
            await db.rollback()
            answer = await _get_answer(db, answer_id)
        else:
            await db.execute(
                update(SupportAnswerRecord)
                .where(SupportAnswerRecord.answer_id == answer_id)
                .values(upvotes=SupportAnswerRecord.upvotes + 1)
                .execution_options(synchronize_session=False)
            )
            await db.refresh(answer)

    return SupportAnswerResponse.from_record(answer)


@router.post("/answers/{answer_id}/accept", response_model=SupportAnswerResponse)
async def accept_answer(
    answer_id: str,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark an answer as the one that solved the question.

    Only the asker can make that call. Accepting a second answer moves the mark
    rather than adding a second: the question is resolved by exactly one
    answer, and the previous one is un-accepted in the same transaction.
    """
    answer = await _get_answer(db, answer_id)
    question = await _get_question(db, answer.question_id)

    if question.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the question author can accept an answer",
        )

    if not answer.is_accepted:
        await db.execute(
            update(SupportAnswerRecord)
            .where(SupportAnswerRecord.question_id == question.question_id)
            .values(is_accepted=False)
            .execution_options(synchronize_session=False)
        )
        await db.execute(
            update(SupportAnswerRecord)
            .where(SupportAnswerRecord.answer_id == answer.answer_id)
            .values(is_accepted=True)
            .execution_options(synchronize_session=False)
        )
        await db.execute(
            update(SupportQuestionRecord)
            .where(SupportQuestionRecord.question_id == question.question_id)
            .values(is_resolved=True)
            .execution_options(synchronize_session=False)
        )
        await db.refresh(answer)

    return SupportAnswerResponse.from_record(answer)
