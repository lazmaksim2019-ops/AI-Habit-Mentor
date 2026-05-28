import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    HabitCreateBatchRequest,
    HabitCreateRequest,
    HabitLogRequest,
    HabitLogResponse,
    HabitResponse,
    HabitsListResponse,
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
        select(UserHabit).where(UserHabit.user_uuid == user_uuid)
    )
    habits = result.scalars().all()
    if not habits:
        return "У пользователя пока нет записанных привычек."

    lines = ["Привычки пользователя:"]
    for h in habits:
        status = "выполнена" if h.is_completed else "не выполнена"
        lines.append(f"- {h.title} [{h.category}] — {status}")
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


def _build_system_prompt(habits_context: str, memory_context: str, gender: str = "male") -> str:
    gender_instruction = (
        "Обращайся к пользователю в женском роде (готова, сделала, ты молодец)."
        if gender == "female"
        else "Обращайся к пользователю в мужском роде (готов, сделал, ты молодец)."
    )
    return f"""Ты — AI-Mentor, высокотехнологичная система когнитивного инжиниринга. Твоя цель — перестроить автоматизмы пользователя и сформировать у него устойчивую целевую доминанту.

ПРАВИЛА ИНТЕРФЕЙСА И ЛОГИКИ:
1. Ты общаешься строго, лаконично, без эзотерики, "успешного успеха" и пустой мотивации. Только научный, системный и инженерный подход.
2. В конце каждого ответа ты ОБЯЗАН предложить от 1 до 3 конкретных, измеримых микро-действий (привычек/операторов), обёрнутых в тег [ADD_HABIT: ...]. Пример: "Предлагаю добавить: [ADD_HABIT: Назначить День Х] и [ADD_HABIT: Выбросить сигареты]."
3. Текст для тега [ADD_HABIT: ...] должен быть ультра-коротким действием (до 40 символов). Никаких "Выбери дату отказа", только: "Назначить День Х", "Выбросить триггеры", "Купить замену".

{gender_instruction}

{habits_context}

Контекст из прошлых диалогов пользователя (долгосрочная память):
{memory_context or "Прошлых диалогов нет."}

СТРАТЕГИЯ ВЕДЕНИЯ К ЦЕЛИ:
- Не задавай по 5 вопросов за раз. Один шаг — один точечный вопрос.
- Сначала зафиксируй точку старта (День Х), затем изолируй триггеры, затем внедри замещающее действие. Веди пользователя по этой архитектурной цепочке.
- Используй правильные склонения исходя из переданного пола пользователя.
- Не запрашивай персональные данные пользователя."""


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

    habits_context = await _get_user_habits_context(user_uuid, session)

    system_prompt = _build_system_prompt(habits_context, memory_context, gender=request.gender)

    history: list = []
    ai_reply = await ai_provider.generate_response(system_prompt, history, cleaned_message)

    background_tasks.add_task(
        _save_memory_background,
        user_uuid,
        cleaned_message,
        ai_reply,
        ai_provider,
    )

    return ChatResponse(reply=ai_reply)


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
        title=request.title,
        category=request.category,
        is_completed=request.is_completed,
    )
    session.add(habit)
    await session.commit()
    await session.refresh(habit)

    logger.info(
        "Logged habit '%s' for user %s (completed=%s)",
        habit.title,
        habit.user_uuid,
        habit.is_completed,
    )

    return HabitLogResponse(
        id=habit.id,
        title=habit.title,
        category=habit.category,
        is_completed=habit.is_completed,
        updated_at=habit.updated_at,
    )


@router.get("/api/habits", response_model=HabitsListResponse)
async def get_habits(
    telegram_id: int = Query(..., description="Telegram user ID"),
    session: AsyncSession = Depends(get_async_session),
):
    user_uuid = await _get_or_create_user(telegram_id, session)
    result = await session.execute(
        select(UserHabit)
        .where(UserHabit.user_uuid == user_uuid)
        .order_by(UserHabit.updated_at.desc())
        .limit(200)
    )
    habits = result.scalars().all()
    return HabitsListResponse(
        habits=[
            HabitResponse(
                id=h.id,
                title=h.title,
                category=h.category,
                is_completed=h.is_completed,
                updated_at=h.updated_at,
                created_at=h.updated_at,
            )
            for h in habits
        ]
    )


@router.post("/api/habits/batch-create")
async def batch_create_habits(
    request: HabitCreateBatchRequest,
    session: AsyncSession = Depends(get_async_session),
):
    user_uuid = await _get_or_create_user(request.telegram_id, session)
    created = []
    for h in request.habits:
        habit = UserHabit(
            user_uuid=user_uuid,
            title=h.title,
            category=h.category,
            is_completed=False,
        )
        session.add(habit)
        created.append(habit)
    await session.commit()
    for habit in created:
        await session.refresh(habit)

    logger.info("Batch created %d habits for user %s", len(created), user_uuid)
    return HabitsListResponse(
        habits=[
            HabitResponse(
                id=h.id,
                title=h.title,
                category=h.category,
                is_completed=h.is_completed,
                updated_at=h.updated_at,
                created_at=h.updated_at,
            )
            for h in created
        ]
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

    # Try a quick Gemini ping
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
