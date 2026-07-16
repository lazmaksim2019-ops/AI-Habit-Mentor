from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ChatHistoryItem(BaseModel):
    role: str = Field(..., pattern="^(user|ai)$", description="Message role: user or ai")
    text: str = Field(..., description="Message text (parsed, without JSON wrappers)")


class ChatRequest(BaseModel):
    telegram_id: int = Field(..., description="Telegram user ID")
    message: str = Field(..., min_length=1, max_length=4096, description="User message text")
    gender: str = Field(
        default="male", pattern="^(male|female)$", description="User grammatical gender for AI responses"
    )
    history: list[ChatHistoryItem] = Field(default=[], description="Recent chat history for context")
    phase: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Current K-O-D phase detected by frontend (1=diagnosis, 2=triggers, 3=operators)",
    )


class ChatResponse(BaseModel):
    reply: str = Field(..., description="AI assistant clean message text (extracted from JSON, without markdown)")
    action: dict = Field(
        default={"type": "NONE", "payload": {}}, description="Structured action with widget_type if applicable"
    )


class MetaKOD(BaseModel):
    category: str = Field(default="", description="K-O-D category")
    operator: str = Field(default="", description="K-O-D operator")
    determination: str = Field(default="", description="K-O-D determination")


class TriggerLog(BaseModel):
    timestamp: str = Field(default="", description="ISO datetime of trigger")
    intensity: int = Field(default=1, ge=1, le=10, description="Trigger intensity 1-10")
    note: str = Field(default="", description="Optional user note")


class HabitLogRequest(BaseModel):
    telegram_id: int | None = Field(default=None, description="Telegram user ID")
    user_uuid: UUID | None = Field(default=None, description="Anonymous user UUID")
    title: str = Field(..., min_length=1, max_length=255, description="Habit name")
    category: str = Field(default="general", max_length=100, description="Habit category")
    is_completed: bool = Field(default=True, description="Completion status")


class HabitCreateItem(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Habit name")
    category: str = Field(default="custom", max_length=100, description="Habit category")
    type: str = Field(default="pre_destruction", pattern="^(pre_destruction|destruction|stabilization)$")
    meta_kod: MetaKOD = Field(default_factory=MetaKOD)


class HabitCreateBatchRequest(BaseModel):
    telegram_id: int = Field(..., description="Telegram user ID")
    habits: list[HabitCreateItem] = Field(..., min_length=1, max_length=20)


class SetTargetDateRequest(BaseModel):
    telegram_id: int = Field(..., description="Telegram user ID")
    name: str = Field(..., min_length=1, max_length=255, description="Habit name")
    target_date: str = Field(..., description="Target date in YYYY-MM-DD format")
    type: str = Field(default="pre_destruction", pattern="^(pre_destruction|destruction|stabilization)$")


class HabitLogResponse(BaseModel):
    id: str
    title: str
    category: str
    is_completed: bool
    updated_at: datetime


class LogTriggerRequest(BaseModel):
    telegram_id: int = Field(..., description="Telegram user ID")
    habit_id: str = Field(..., description="Habit UUID")
    intensity: int = Field(default=1, ge=1, le=10, description="Trigger intensity")
    note: str = Field(default="", max_length=500, description="Optional note")


class HabitResponse(BaseModel):
    id: str
    name: str
    type: str = "pre_destruction"
    category: str = "custom"
    meta_kod: MetaKOD = Field(default_factory=MetaKOD)
    target_date: str | None = None
    status: str = "active"
    logs: list[TriggerLog] = Field(default=[])
    created_at: datetime | None = None
    updated_at: datetime | None = None


class HabitsListResponse(BaseModel):
    habits: list[HabitResponse]
