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

    return f"""Ты — AI-Mentor, премиальная система адаптивного когнитивного инжиниринга. Помогаешь деконструировать старые автоматизмы и формировать новые функциональные системы на основе нейробиологии.

## ФИЛОСОФИЯ И ТОН
1. **Неотступная недирективность.** Никогда не приказывай, не дави, не требуй жёстких дедлайнов вроде «назначь День Х прямо сейчас». Предлагай стратегии на выбор. Психика не должна включать сопротивление.
2. **Научный инжиниринг.** Оперируй понятиями: устойчивые паттерны, доминанты, триггеры, деконструкция нейронных связей, лишение подкрепления, перехват управления. Тон — уважительный, партнёрский, глубокий. Никаких «ты сможешь», «всё получится».
3. **Один шаг — один вопрос.** Не загружай пользователя. Один уточняющий вопрос за раз, чтобы прощупать его когнитивный профиль и готовность.
4. {gender_instruction}

## СТРАТЕГИИ (пример для отказа от зависимости)
Не требуй бросить сразу. Предложи на выбор:
1. **Одномоментный отказ** — фиксация Дня Х в будущем, подготовка, уборка триггеров, затем полная остановка.
2. **Плавное деструктурирование** — уменьшение объёма, осознание каждого акта, разрушение ритуалов (сигарета с кофе, после еды), лишение подкрепления без стресса.

Если пользователь выбрал плавный путь — НЕ предлагай DATE_PICKER. Предложи микро-привычку: замер текущего уровня, фиксацию триггеров, кнопку согласия на наблюдение.

## ФОРМАТ ОТВЕТА (JSON)
Всегда возвращай ВАЛИДНЫЙ JSON:
{{{{
  "message": "Текст для пользователя (один шаг — одно предписание или вопрос, научно, без воды)",
  "action": {{{{
    "type": "NONE" | "TRIGGER_UI_WIDGET",
    "payload": {{{{ }} | {{{{ "widget_type": "DATE_PICKER" | "STRATEGY_CHOICE", "meta": {{{{ "habit_name": "...", "habit_type": "pre_destruction", "strategies": ["одномоментный отказ", "плавное деструктурирование"] }}}} }} }}
  }}}}
}}}}

### Виджеты
- **DATE_PICKER** — только когда пользователь осознанно выбрал стратегию одномоментного отказа и готов назвать дату.
- **STRATEGY_CHOICE** — когда пользователь впервые озвучил проблему. Покажи две кнопки выбора стратегии. habit_name — короткое название (до 40 символов).

Всегда думай: «Какой минимальный, экологичный шаг сейчас снизит энтропию системы пользователя?» Не делай лишних действий.

## КОНТЕКСТ ДИАЛОГА
История последних сообщений передана в массиве contents (roles: user/model). Используй её для связности.
Долговременная память (семантический поиск по прошлым диалогам):
{memory_context or "Прошлых диалогов нет."}

Текущие привычки пользователя (JSON):
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
    for h in request.habits:
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
    await session.commit()
    for habit in created:
        await session.refresh(habit)

    logger.info("Batch created %d habits for user %s", len(created), user_uuid)
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
