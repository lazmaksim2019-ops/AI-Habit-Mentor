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
    result = await session.execute(select(UserLink).where(UserLink.telegram_id == telegram_id))
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
        lines.append(
            json.dumps(
                {
                    "id": str(h.id),
                    "name": h.name,
                    "type": h.type,
                    "category": h.category,
                    "status": h.status,
                    "target_date": h.target_date.isoformat() if h.target_date else None,
                    "meta_kod": meta,
                },
                ensure_ascii=False,
            )
        )
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
        items.append(
            json.dumps(
                {
                    "id": str(h.id),
                    "name": h.name,
                    "type": h.type,
                    "category": h.category,
                    "status": h.status,
                    "target_date": h.target_date.isoformat() if h.target_date else None,
                    "meta_kod": meta,
                    "logs_count": len(h.logs or []),
                },
                ensure_ascii=False,
            )
        )
    return "[\n" + ",\n".join(items) + "\n]" if items else "[]"


def _detect_phase(habits_data: list[UserHabit], history: list) -> int:
    """Detect K-O-D phase from habits + chat history.
    Phase 1 = diagnosis (no strategy chosen, no habits)
    Phase 2 = trigger isolation (strategy chosen, habits exist, no operators deployed)
    Phase 3 = operator engineering (micro-habits with meta_kod.operator exist)
    """
    if not habits_data:
        return 1

    # If any habit has a filled operator in meta_kod → Phase 3
    for h in habits_data:
        meta = h.meta_kod or {}
        if meta.get("operator"):
            return 3

    # If habits exist but no operators → Phase 2
    return 2


def _build_system_prompt(
    habits_data: list[UserHabit],
    memory_context: str,
    gender: str = "male",
    user_name: str = "",
    current_phase: int = 1,
    strategy_chosen: bool = False,
) -> str:
    gender_instruction = "female" if gender == "female" else "male"
    name_instruction = f"Имя: {user_name}. Обращайся по имени раз в 4-5 реплик." if user_name else "Имя не указано."
    habits_json = _serialize_habits_context(habits_data)

    # Если стратегия уже выбрана — не предлагаем STRATEGY_CHOICE
    phase_map = {
        1: "ФАЗА 1: диагностика. Стратегия НЕ выбрана. Локализуй категорию, предложи STRATEGY_CHOICE или DATE_PICKER.",
        2: "ФАЗА 2: изоляция триггеров. operator пуст. Исследуй триггеры, один тезис apraqueen один вопрос.",
        3: "ФАЗА 3: операторы. Спроектируй category, operator (до 40 симв.), determination.",
    }
    
    # Если стратегия выбрана, но фаза 1 — переходим к фазе 2
    if strategy_chosen and current_phase == 1:
        phase_block = "ФАЗА 2: изоляция триггеров. Стратегия выбрана. Исследуй триггеры, один тезис — один вопрос."
    else:
        phase_block = phase_map.get(current_phase, phase_map[1])

    return f"""## РОЛЬ
Ты — AI-Mentor, системный архитектор поведения. Протокол Мета-К.О.Д. (автор Лазаренко А.).
Два направления: деконструкция (разрушение автоматизмов) и формирование (наработка новых).
Опираешься на теорию Анохина и Ухтомского.

## ФАЗА: {current_phase}
{phase_block}

## ЗАПРЕТЫ
1. Никаких банальных советов («вдохни», «выпей воды»).
2. Не директивен (не «ты должен»). Гипотезы.
3. ОДИН вопрос за ответ. Завершай вопросом.
4. Без маркдауна в message.
5. Если пользователь предлагает «терпеть» — деконструируй (кортизоловый срыв).

## АДАПТАЦИЯ
Род: {gender_instruction}. {name_instruction}

## НАПРАВЛЕНИЕ
Деконструкция (избавиться) или формирование (наработать).

## ФОРМАТ ВЫВОДА (СТРОГИЙ JSON)
{{{{"message": "текст без маркдауна, с вопросом","action":{{{{"type":"NONE|TRIGGER_UI_WIDGET","payload":{{{{"widget_type":"STRATEGY_CHOICE|DATE_PICKER","meta":{{{{"habit_name":"...","strategies":["резко","плавно"]}}}}}}}}}}}}}}}}

## КОНТЕКСТ
Память: {memory_context or "Новый паттерн."}
Привычки: {habits_json}"""


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
        logs=[TriggerLog(**log_item) if isinstance(log_item, dict) else TriggerLog() for log_item in logs_raw],
        created_at=h.created_at,
        updated_at=h.updated_at,
    )


def _clean_json_from_response(raw: str) -> str:
    """Extract JSON string from model output, handling markdown ```json fences."""
    s = raw.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and (lines[0].startswith("```json") or lines[0] == "```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s


@router.post("/chat", response_model=ChatResponse)
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

    # Detect phase server-side (authoritative) — falls back to frontend phase if no habits yet
    server_phase = _detect_phase(habits_data, request.history or [])
    current_phase = max(server_phase, request.phase)  # use most advanced phase

    system_prompt = _build_system_prompt(
        habits_data, memory_context, gender=request.gender, user_name=request.user_name, current_phase=current_phase, strategy_chosen=request.strategy_chosen
    )

    # Build history from request (frontend sends parsed chat history)
    history = [{"role": "assistant" if m.role == "ai" else "user", "content": m.text} for m in (request.history or [])]
    raw_ai_reply = await ai_provider.generate_response(system_prompt, history, cleaned_message)

    # Parse JSON from Gemini response
    clean_json = _clean_json_from_response(raw_ai_reply)
    user_message = raw_ai_reply
    action_data: dict = {"type": "NONE", "payload": {}}

    try:
        parsed = json.loads(clean_json)
        user_message = parsed.get("message", raw_ai_reply)
        action_data = parsed.get("action", {"type": "NONE", "payload": {}})
    except json.JSONDecodeError:
        logger.error("Gemini returned non-JSON response, forwarding raw: %.200s", raw_ai_reply)

    background_tasks.add_task(
        _save_memory_background,
        user_uuid,
        cleaned_message,
        user_message,
        ai_provider,
    )

    return ChatResponse(reply=user_message, action=action_data)


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Streaming version of /chat.
    Returns Server-Sent Events stream of tokens.
    """
    ai_provider = GeminiProvider(
        api_key=settings.GEMINI_API_KEY,
        model=settings.GEMINI_MODEL,
        embedding_model=settings.GEMINI_EMBEDDING_MODEL,
        proxy_url=settings.proxy_url,
    )

    user_uuid = await _get_or_create_user(request.telegram_id, session)
    cleaned_message = await anonymize_text(request.message)

    # Параллелизация: эмбеддинг + запрос привычек одновременно
    import asyncio

    embedding_task = asyncio.create_task(ai_provider.get_embedding(cleaned_message))
    habits_task = asyncio.create_task(
        session.execute(
            select(UserHabit).where(UserHabit.user_uuid == user_uuid).order_by(UserHabit.created_at.desc()).limit(50)
        )
    )

    embedding, habits_result = await asyncio.gather(embedding_task, habits_task)
    habits_data = list(habits_result.scalars().all())
    memory_context = await get_relevant_memory(session, user_uuid, embedding)

    server_phase = _detect_phase(habits_data, request.history or [])
    current_phase = max(server_phase, request.phase)

    system_prompt = _build_system_prompt(
        habits_data, memory_context, gender=request.gender, user_name=request.user_name, current_phase=current_phase, strategy_chosen=request.strategy_chosen
    )

    history = [{"role": "assistant" if m.role == "ai" else "user", "content": m.text} for m in (request.history or [])]

    from fastapi.responses import StreamingResponse

    async def event_stream():
        full_text = ""
        async for token, accumulated in ai_provider.generate_response_streaming(
            system_prompt, history, cleaned_message
        ):
            if token:
                full_text = accumulated
                yield f"data: {json.dumps({'token': token, 'text': accumulated})}\n\n"
            else:
                full_text = accumulated

        # Парсим JSON из полного ответа
        clean_json = _clean_json_from_response(full_text)
        user_message = full_text
        action_data = {"type": "NONE", "payload": {}}
        try:
            parsed = json.loads(clean_json)
            user_message = parsed.get("message", full_text)
            action_data = parsed.get("action", {"type": "NONE", "payload": {}})
        except json.JSONDecodeError:
            logger.error("Gemini stream returned non-JSON: %.200s", full_text)

        # Сохраняем в векторную память
        background_tasks.add_task(_save_memory_background, user_uuid, cleaned_message, user_message, ai_provider)

        yield f"data: {json.dumps({'done': True, 'message': user_message, 'action': action_data})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/habits", response_model=HabitsListResponse)
async def get_habits(
    telegram_id: int = Query(..., description="Telegram user ID"),
    session: AsyncSession = Depends(get_async_session),
):
    user_uuid = await _get_or_create_user(telegram_id, session)
    result = await session.execute(
        select(UserHabit).where(UserHabit.user_uuid == user_uuid).order_by(UserHabit.created_at.desc()).limit(200)
    )
    habits = result.scalars().all()
    return HabitsListResponse(habits=[_habit_to_response(h) for h in habits])


@router.post("/habits/batch-create")
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
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)[:200]}") from e

    logger.info("Batch created %d habits for user %s (errors: %d)", len(created), user_uuid, len(errors))
    return HabitsListResponse(habits=[_habit_to_response(h) for h in created])


@router.post("/habits/set-target-date")
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


@router.post("/habits/log-trigger")
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
    logs.append(
        {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "intensity": request.intensity,
            "note": request.note,
        }
    )
    habit.logs = logs

    await session.commit()
    await session.refresh(habit)

    logger.info("Logged trigger for habit '%s' user %s (intensity=%d)", habit.name, user_uuid, request.intensity)
    return _habit_to_response(habit)


@router.post("/habits/log", response_model=HabitLogResponse)
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


@router.get("/diag")
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
        async with httpx.AsyncClient(**provider._client_kwargs) as client:  # type: ignore[arg-type]
            resp = await client.post(url, json=test_payload)
            results["gemini_test_status"] = resp.status_code
            if resp.status_code == 200:
                data = resp.json()
                results["gemini_test_ok"] = True
                results["gemini_test_reply"] = (
                    data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")[:200]
                )
            else:
                results["gemini_test_ok"] = False
                results["gemini_test_body"] = resp.text[:500]
    except Exception as e:
        results["gemini_test_ok"] = False
        results["gemini_test_error"] = str(e)[:500]
        import traceback

        results["gemini_test_traceback"] = traceback.format_exc()[:500]

    return results


@router.post("/webhook")
async def telegram_webhook(update: dict):
    """Telegram Bot webhook endpoint.
    Принимает апдейты от Telegram Bot API и отправляет ответ через AI-ментора.
    """
    import httpx

    message = update.get("message", {})
    if not message:
        return {"ok": True}

    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if not chat_id or not text:
        return {"ok": True}

    # Пропускаем команды
    if text.startswith("/"):
        if text == "/start":
            reply_text = (
                "🧠 *Neuro-Adaptive AI Habit Mentor*\n\n"
                "Я — AI-ментор по привычкам. Нажми кнопку ниже, чтобы открыть Mini App и начать работу!"
            )
            async with httpx.AsyncClient(timeout=30) as client:
                await client.post(
                    f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": reply_text,
                        "parse_mode": "Markdown",
                        "reply_markup": {
                            "inline_keyboard": [
                                [
                                    {
                                        "text": "🚀 Открыть Mini App",
                                        "web_app": {"url": "https://ai-habit-mentor.onrender.com/"},
                                    }
                                ]
                            ]
                        },
                    },
                )
        return {"ok": True}

    # Для любых сообщений — отправляем кнопку открытия Mini App
    reply_text = (
        "🧠 *Neuro-Adaptive AI Habit Mentor*\n\n"
        "Весь функционал AI-ментора доступен в Mini App. Нажми кнопку ниже, чтобы открыть!"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": reply_text,
                "parse_mode": "Markdown",
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {
                                "text": "🚀 Открыть Mini App",
                                "web_app": {"url": "https://ai-habit-mentor.onrender.com/"},
                            }
                        ]
                    ]
                },
            },
        )
    return {"ok": True}
