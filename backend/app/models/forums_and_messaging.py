from pydantic import BaseModel, ConfigDict, Field
from app.core.ids import generate_id
from datetime import datetime, timezone
from user import UserRole

# Community Support Models
class Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message_id: str = Field(default_factory=lambda: generate_id("msg"))
    order_id: str
    sender_id: str
    receiver_id: str
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_read: bool = False


class MessageCreate(BaseModel):
    order_id: str
    receiver_id: str
    content: str


class SupportQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question_id: str = Field(default_factory=lambda: generate_id("q"))
    user_id: str
    user_name: str = ""
    user_role: UserRole = UserRole.CUSTOMER
    question: str
    category: str = "general"  # general, delivery, payment, restaurant, technical
    is_resolved: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SupportAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    answer_id: str = Field(default_factory=lambda: generate_id("a"))
    question_id: str
    user_id: str
    user_name: str = ""
    user_role: UserRole
    answer: str
    is_accepted: bool = False
    upvotes: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class QuestionCreate(BaseModel):
    question: str
    category: str = "general"


class AnswerCreate(BaseModel):
    question_id: str
    answer: str


# Forum Models
class ForumCategory(BaseModel):
    model_config = ConfigDict(extra="ignore")
    category_id: str = Field(default_factory=lambda: generate_id("cat"))
    name: str
    description: str = ""
    is_regional: bool = False  # To distinguish between regional and general forums


class ForumPost(BaseModel):
    model_config = ConfigDict(extra="ignore")
    post_id: str = Field(default_factory=lambda: generate_id("post"))
    category_id: str
    user_id: str
    user_name: str
    user_role: UserRole
    title: str
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ForumReply(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reply_id: str = Field(default_factory=lambda: generate_id("reply"))
    post_id: str
    user_id: str
    user_name: str
    user_role: UserRole
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ForumPostCreate(BaseModel):
    category_id: str
    title: str
    content: str


class ForumReplyCreate(BaseModel):
    post_id: str
    content: str
