from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    telegram_id: int = Field(..., description="Telegram user ID")
    message: str = Field(..., min_length=1, max_length=4096, description="User message text")
    gender: str = Field(default="male", pattern="^(male|female)$", description="User grammatical gender for AI responses")


class ChatResponse(BaseModel):
    reply: str = Field(..., description="AI assistant reply")


class HabitLogRequest(BaseModel):
    telegram_id: int | None = Field(default=None, description="Telegram user ID (alternative to user_uuid)")
    user_uuid: UUID | None = Field(default=None, description="Anonymous user UUID")
    title: str = Field(..., min_length=1, max_length=255, description="Habit title")
    category: str = Field(default="general", max_length=100, description="Habit category")
    is_completed: bool = Field(default=True, description="Completion status")


class HabitCreateRequest(BaseModel):
    telegram_id: int = Field(..., description="Telegram user ID")
    title: str = Field(..., min_length=1, max_length=255, description="Habit title")
    category: str = Field(default="custom", max_length=100, description="Habit category")


class HabitCreateBatchRequest(BaseModel):
    telegram_id: int = Field(..., description="Telegram user ID")
    habits: list[HabitCreateRequest] = Field(..., min_length=1, max_length=20)


class HabitLogResponse(BaseModel):
    id: int
    title: str
    category: str
    is_completed: bool
    updated_at: datetime


class HabitResponse(BaseModel):
    id: int
    title: str
    category: str
    is_completed: bool
    updated_at: datetime
    created_at: datetime | None = None


class HabitsListResponse(BaseModel):
    habits: list[HabitResponse]
