import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    HabitCreateBatchRequest,
    HabitLogRequest,
    HabitLogResponse,
    HabitResponse,
    HabitsListResponse,
    LogTriggerRequest,
    MetaKOD,
    SetTargetDateRequest,
    TriggerLog,
)
from app.core.config import settings
from app.database.models import UserHabit, UserLink, UserVectorMemory
from app.database.repository import get_relevant_memory
from app.database.session import get_async_session, get_session_maker
from app.services.ai.gemini import GeminiProvider
from app.services.anonymizer import anonymize_text

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_or_create_user(telegram_id: int, session: AsyncSession) -> uuid.UUID:
    result = await session.execute(
        select(UserLink).where(UserLink.telegram_id == telegram_id)
    )
    user_link = result.scalar_one_or_none()
    if user_link is not None:
        return user_link.user_uuid

    new_uuid = uuid.uuid4()
    user_link = UserLink(user_uuid=new_uuid, telegram_id=telegram_id)
    session.add(user_link)
    await session.commit()
    logger.info("Created anonymous user_uuid=%s for telegram_id=%d", new_uuid, telegram_id)
    return new_uuid


async def _get_user_habits_context(user_uuid: uuid.UUID, session: AsyncSession) -> str:
    result = await session.execute(
        select(UserHabit).where(UserHabit.user_uuid == user_uuid).order_by(UserHabit.created_at.desc()).limit(50)
    )
    habits = result.scalars().all()
    if not habits:
        return "У пользователя пока нет записанных привычек."

    lines = ["Привычки пользователя (JSON-массив для парсинга):"]
    for h in habits:
        meta = h.meta_kod or {}
        lines.append(json.dumps({
            "id": str(h.id),
            "name": h.name,
            "type": h.type,
            "category": h.category,
            "status": h.status,
            "target_date": h.target_date.isoformat() if h.target_date else None,
            "meta_kod": meta,
        }, ensure_ascii=False))
    return "\n".join(lines)


async def _save_memory_background(
    user_uuid: uuid.UUID,
    cleaned_question: str,
    ai_answer: str,
    ai_provider: GeminiProvider,
):
    try:
        async with get_session_maker()() as session:
            combined_text = f"Вопрос: {cleaned_question}\nОтвет: {ai_answer}"
            embedding = await ai_provider.get_embedding(combined_text)
            if not embedding:
                logger.warning("Empty embedding for memory, skipping save")
                return

            memory = UserVectorMemory(
                user_uuid=user_uuid,
                embedding_vector=embedding,
                content_text=combined_text,
            )
            session.add(memory)
            await session.commit()
            logger.info("Saved vector memory for user %s", user_uuid)
    except Exception as e:
        logger.error("Failed to save vector memory for user %s: %s", user_uuid, e)


def _serialize_habits_context(habits_data: list[UserHabit]) -> str:
    items = []
    for h in habits_data:
        meta = h.meta_kod or {}
        items.append(json.dumps({
            "id": str(h.id),
            "name": h.name,
            "type": h.type,
            "category": h.category,
            "status": h.status,
            "target_date": h.target_date.isoformat() if h.target_date else None,
            "meta_kod": meta,
            "logs_count": len(h.logs or []),
        }, ensure_ascii=False))
    return "[\n" + ",\n".join(items) + "\n]" if items else "[]"


def _build_system_prompt(habits_data: list[UserHabit], memory_context: str, gender: str = "male") -> str:
    gender_instruction = (
        "Обращайся к пользователю в женском роде (готова, сделала)."
        if gender == "female"
        else "Обращайся к пользователю в мужском роде (готов, сделал)."
    )

    habits_json = _serialize_habits_context(habits_data)

    return f"""Ты — AI-Mentor, ядро премиальной системы адаптивного когнитивного инжиниринга.

## I. ТОН И СТИЛЬ
1. **Партнёрство и недирективность.** Никогда не приказывай, не дави, не требуй дат. Предлагай как инженерные гипотезы.
2. **Простой язык.** Объясняй научные концепции без тяжёлой терминологии. Тон уважительный, точный, без «успешного успеха».
3. **Один шаг — один вопрос.** Не загружай пользователя.
4. {gender_instruction}

## II. СТРОГАЯ СТРУКТУРА ДИАЛОГА (СТЕЙТ-МАШИНА)
Ты ведёшь пользователя строго последовательно по 3 фазам. Переход на следующую фазу — ТОЛЬКО после ответа пользователя. Возврат на пройденную фазу ЗАПРЕЩЁН.

### ФАЗА 1: ДИАГНОСТИКА И ВЫБОР СТРАТЕГИИ
- Выяви привычку, предложи два пути: резко бросить (с Днём Х) или плавно снижать.
- Виджет STRATEGY_CHOICE — ТОЛЬКО ОДИН РАЗ. Как только пользователь ответил — фаза 1 блокируется навсегда.

### ФАЗА 2: ИЗОЛЯЦИЯ АВТОМАТИЗМОВ
- Изучи контекст срыва. Один вопрос за раз: «В какие моменты тянет сильнее всего?», «Что запускает ритуал?».
- Помоги включить наблюдателя. Никаких требований бросить.

### ФАЗА 3: ВНЕДРЕНИЕ ОПЕРАТОРОВ (ТРЕКЕР)
- Сформируй микро-привычки (до 40 символов) и отправь в action.

## III. ФОРМАТ ОТВЕТА (СТРОГИЙ JSON)
{{{{
  "message": "Текст пользователю (просто, коротко, по-человечески)",
  "action": {{{{
    "type": "NONE" | "TRIGGER_UI_WIDGET",
    "payload": {{{{ }} | {{{{ "widget_type": "STRATEGY_CHOICE", "meta": {{{{ "habit_name": "...", "strategies": ["резко бросить", "плавно снижать"] }}}} }} | {{{{ "widget_type": "DATE_PICKER", "meta": {{{{ "habit_name": "...", "habit_type": "pre_destruction" }}}} }}
  }}}}
}}}}

### ПРАВИЛА ВИДЖЕТОВ
- STRATEGY_CHOICE — ТОЛЬКО в Фазе 1, один раз. Если стратегия уже обсуждалась в истории — НЕ ИСПОЛЬЗУЙ.
- DATE_PICKER — только если пользователь сам выбрал «резко бросить» и готов назвать дату.
- Если виджет не нужен: action = {{{{ "type": "NONE", "payload": {{}} }}}}

## IV. КОНТЕКСТ
Последние сообщения в contents. Долговременная память:
{memory_context or "Прошлых диалогов нет."}

Привычки пользователя:
{habits_json}"""


def _habit_to_response(h: UserHabit) -> HabitResponse:
    meta = h.meta_kod or {}
    logs_raw = h.logs or []
    return HabitResponse(
        id=str(h.id),
        name=h.name,
        type=h.type,
        category=h.category,
        meta_kod=MetaKOD(
            category=meta.get("category", ""),
            operator=meta.get("operator", ""),
            determination=meta.get("determination", ""),
        ),
        target_date=h.target_date.isoformat() if h.target_date else None,
        status=h.status,
        logs=[TriggerLog(**l) if isinstance(l, dict) else TriggerLog() for l in logs_raw],
        created_at=h.created_at,
        updated_at=h.updated_at,
    )


@router.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_session),
):
    ai_provider = GeminiProvider(
        api_key=settings.GEMINI_API_KEY,
        model=settings.GEMINI_MODEL,
        embedding_model=settings.GEMINI_EMBEDDING_MODEL,
        proxy_url=settings.proxy_url,
    )

    user_uuid = await _get_or_create_user(request.telegram_id, session)

    cleaned_message = await anonymize_text(request.message)

    embedding = await ai_provider.get_embedding(cleaned_message)

    memory_context = await get_relevant_memory(session, user_uuid, embedding)

    result = await session.execute(
        select(UserHabit).where(UserHabit.user_uuid == user_uuid).order_by(UserHabit.created_at.desc()).limit(50)
    )
    habits_data = list(result.scalars().all())

    system_prompt = _build_system_prompt(habits_data, memory_context, gender=request.gender)

    # Build history from request (frontend sends parsed chat history)
    history = [{"role": "assistant" if m.role == "ai" else "user", "content": m.text} for m in (request.history or [])]
    ai_reply = await ai_provider.generate_response(system_prompt, history, cleaned_message)

    background_tasks.add_task(
        _save_memory_background,
        user_uuid,
        cleaned_message,
        ai_reply,
        ai_provider,
    )

    return ChatResponse(reply=ai_reply)


@router.get("/api/habits", response_model=HabitsListResponse)
async def get_habits(
    telegram_id: int = Query(..., description="Telegram user ID"),
    session: AsyncSession = Depends(get_async_session),
):
    user_uuid = await _get_or_create_user(telegram_id, session)
    result = await session.execute(
        select(UserHabit)
        .where(UserHabit.user_uuid == user_uuid)
        .order_by(UserHabit.created_at.desc())
        .limit(200)
    )
    habits = result.scalars().all()
    return HabitsListResponse(habits=[_habit_to_response(h) for h in habits])


@router.post("/api/habits/batch-create")
async def batch_create_habits(
    request: HabitCreateBatchRequest,
    session: AsyncSession = Depends(get_async_session),
):
    user_uuid = await _get_or_create_user(request.telegram_id, session)
    created = []
    errors = []
    for h in request.habits:
        try:
            meta = h.meta_kod or MetaKOD()
            habit = UserHabit(
                user_uuid=user_uuid,
                name=h.name,
                type=h.type,
                category=h.category,
                meta_kod=meta.model_dump(),
                status="active",
                logs=[],
            )
            session.add(habit)
            created.append(habit)
        except Exception as e:
            errors.append({"name": h.name, "error": str(e)})
            logger.error("Failed to create habit '%s' for user %s: %s", h.name, user_uuid, e)

    if created:
        try:
            await session.commit()
            for habit in created:
                await session.refresh(habit)
        except Exception as e:
            logger.error("Batch commit failed for user %s: %s", user_uuid, e)
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)[:200]}")

    logger.info("Batch created %d habits for user %s (errors: %d)", len(created), user_uuid, len(errors))
    return HabitsListResponse(habits=[_habit_to_response(h) for h in created])


@router.post("/api/habits/set-target-date")
async def set_habit_target_date(
    request: SetTargetDateRequest,
    session: AsyncSession = Depends(get_async_session),
):
    user_uuid = await _get_or_create_user(request.telegram_id, session)

    result = await session.execute(
        select(UserHabit)
        .where(UserHabit.user_uuid == user_uuid, UserHabit.name == request.name)
        .order_by(UserHabit.created_at.desc())
        .limit(1)
    )
    habit = result.scalar_one_or_none()

    if habit is None:
        habit = UserHabit(
            user_uuid=user_uuid,
            name=request.name,
            type=request.type,
            category="custom",
            meta_kod={},
            status="active",
            target_date=datetime.fromisoformat(request.target_date),
            logs=[],
        )
        session.add(habit)
    else:
        habit.target_date = datetime.fromisoformat(request.target_date)
        habit.type = request.type

    await session.commit()
    await session.refresh(habit)

    logger.info("Set target_date for habit '%s' user %s → %s", habit.name, user_uuid, request.target_date)
    return _habit_to_response(habit)


@router.post("/api/habits/log-trigger")
async def log_trigger(
    request: LogTriggerRequest,
    session: AsyncSession = Depends(get_async_session),
):
    user_uuid = await _get_or_create_user(request.telegram_id, session)

    result = await session.execute(
        select(UserHabit).where(UserHabit.id == request.habit_id, UserHabit.user_uuid == user_uuid)
    )
    habit = result.scalar_one_or_none()
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")

    logs = list(habit.logs or [])
    logs.append({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "intensity": request.intensity,
        "note": request.note,
    })
    habit.logs = logs

    await session.commit()
    await session.refresh(habit)

    logger.info("Logged trigger for habit '%s' user %s (intensity=%d)", habit.name, user_uuid, request.intensity)
    return _habit_to_response(habit)


@router.post("/api/habits/log", response_model=HabitLogResponse)
async def log_habit(
    request: HabitLogRequest,
    session: AsyncSession = Depends(get_async_session),
):
    if request.telegram_id is not None:
        user_uuid = await _get_or_create_user(request.telegram_id, session)
    elif request.user_uuid is not None:
        user_uuid = request.user_uuid
    else:
        user_uuid = uuid.uuid4()

    habit = UserHabit(
        user_uuid=user_uuid,
        name=request.title,
        category=request.category,
        type="pre_destruction",
        is_completed=request.is_completed,
        meta_kod={},
        logs=[],
    )
    session.add(habit)
    await session.commit()
    await session.refresh(habit)

    return HabitLogResponse(
        id=str(habit.id),
        title=habit.name,
        category=habit.category,
        is_completed=habit.is_completed,
        updated_at=habit.updated_at,
    )


@router.get("/api/diag")
async def diagnostic():
    results = {
        "api_key_set": bool(settings.GEMINI_API_KEY),
        "api_key_preview": settings.GEMINI_API_KEY[:8] + "..." if settings.GEMINI_API_KEY else "NOT SET",
        "model": settings.GEMINI_MODEL,
        "embedding_model": settings.GEMINI_EMBEDDING_MODEL,
        "proxy_host_set": bool(settings.PROXY_HOST),
        "proxy_port_set": bool(settings.PROXY_PORT),
        "proxy_user_set": bool(settings.PROXY_USER),
        "proxy_url": "configured" if settings.proxy_url else "not configured",
    }

    try:
        import httpx
        provider = GeminiProvider(
            api_key=settings.GEMINI_API_KEY,
            model=settings.GEMINI_MODEL,
            embedding_model=settings.GEMINI_EMBEDDING_MODEL,
            proxy_url=settings.proxy_url,
        )
        test_payload = {
            "contents": [{"parts": [{"text": "Say OK"}]}],
        }
        url = f"{provider.base_url}/models/{provider.model}:generateContent?key={provider.api_key}"
        async with httpx.AsyncClient(**provider._client_kwargs) as client:
            resp = await client.post(url, json=test_payload)
            results["gemini_test_status"] = resp.status_code
            if resp.status_code == 200:
                data = resp.json()
                results["gemini_test_ok"] = True
                results["gemini_test_reply"] = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")[:200]
            else:
                results["gemini_test_ok"] = False
                results["gemini_test_body"] = resp.text[:500]
    except Exception as e:
        results["gemini_test_ok"] = False
        results["gemini_test_error"] = str(e)[:500]
        import traceback
        results["gemini_test_traceback"] = traceback.format_exc()[:500]

    return results
