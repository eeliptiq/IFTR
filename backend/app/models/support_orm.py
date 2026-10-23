"""
SQLAlchemy ORM models for the community support board.

Three tables, because a question, its answers and who agreed with an answer are
different facts:

  * `support_questions` - somebody's question (or, in the driver's route-tips
    screen, a shared tip), with who asked and which category it belongs in.
  * `support_answers` - replies to one question. The `is_accepted` flag is the
    asker's decision; `upvotes` is a running count so the list does not need an
    aggregate on every read.
  * `support_answer_votes` - one row per person per answer. The prototype
    incremented a counter per tap, so one person could vote ten times; this
    table is what makes "one person, one vote" true, and the composite primary
    key is what enforces it even when two taps race.

`user_name` and `user_role` are snapshots rather than joins: the board keeps
showing who said what if the account is later renamed or disabled. Nothing
sensitive is stored here - no addresses, no contact details.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import generate_id
from app.database import Base


class SupportQuestionRecord(Base):
    __tablename__ = "support_questions"

    question_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("q")
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    user_role: Mapped[str] = mapped_column(String(32), nullable=False, default="customer")

    question: Mapped[str] = mapped_column(Text, nullable=False)
    # A short vocabulary, validated at the API edge; stored as a string for the
    # same reason order statuses are (see app/models/general.py).
    category: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="general")

    # Set by the asker accepting an answer. Not derived from the answers table:
    # acceptance is the asker's act, and a question stays open until they make
    # it.
    is_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class SupportAnswerRecord(Base):
    __tablename__ = "support_answers"

    answer_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("a")
    )
    question_id: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    user_role: Mapped[str] = mapped_column(String(32), nullable=False, default="customer")

    answer: Mapped[str] = mapped_column(Text, nullable=False)
    is_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    upvotes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class SupportAnswerVoteRecord(Base):
    """One person's upvote of one answer.

    Composite primary key rather than a surrogate id: the pair is the identity,
    and the database refusing the duplicate is a better guarantee than a
    "has this person voted?" check that can lose a race.
    """

    __tablename__ = "support_answer_votes"

    answer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
