from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    telegram_id: int = Field(..., description="Telegram user ID")
    message: str = Field(..., min_length=1, max_length=4096, description="User message text")


class ChatResponse(BaseModel):
    reply: str = Field(..., description="AI assistant reply")


class HabitLogRequest(BaseModel):
    user_uuid: UUID = Field(..., description="Anonymous user UUID")
    title: str = Field(..., min_length=1, max_length=255, description="Habit title")
    category: str = Field(default="general", max_length=100, description="Habit category")
    is_completed: bool = Field(default=True, description="Completion status")


class HabitLogResponse(BaseModel):
    id: int
    title: str
    category: str
    is_completed: bool
    updated_at: datetime
