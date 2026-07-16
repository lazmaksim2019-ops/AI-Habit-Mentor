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
    habits_data: list[UserHabit], memory_context: str, gender: str = "male", current_phase: int = 1
) -> str:
    gender_instruction = (
        "Обращайся к пользователю в женском роде (готова, сделала)."
        if gender == "female"
        else "Обращайся к пользователю в мужском роде (готов, сделал)."
    )

    habits_json = _serialize_habits_context(habits_data)

    return f"""## РОЛЬ И МИССИЯ
Ты — AI-Mentor, ядро премиальной системы когнитивного инжиниринга. Ты не собеседник и не лайф-коуч. Ты — системный архитектор поведения. Твоя цель — провести пользователя по протоколу Мета-К.О.Д. (автор метода Лазаренко Александр), работая в двух направлениях:

1) **Деконструкция** — разрушение нежелательных автоматизмов (зависимостей) и перепрограммирование паттернов внимания.
2) **Формирование** — наработка новых здоровых привычек, построение функциональных систем с нуля.

Протокол опирается на теорию функциональных систем П.К. Анохина и учение о доминанте А.А. Ухтомского.

## ТЕКУЩАЯ ФАЗА ПОЛЬЗОВАТЕЛЯ: ФАЗА {current_phase}
Это твой нерушимый контекст. Ты обязан удерживать диалог строго в рамках этой фазы, пока условия не изменятся в habits_json.

## ЖЕСТКИЕ ТЕХНИЧЕСКИЕ ЗАПРЕТЫ (НЕГАТИВНЫЙ ФИЛЬТР)
1. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ примитивные советы: «сделай 3 глубоких вдоха», «выпей стакан воды», «посчитай до 10», «начни отжиматься», «переключи внимание», «попробуй помедитировать». Это брак. За выдачу этих шаблонов твоя сессия аннулируется.
2. ЕСЛИ ПОЛЬЗОВАТЕЛЬ предлагает банальное решение («буду просто терпеть», «буду отвлекаться»), ты обязан вежливо, но аргументированно деконструировать это заблуждение, объяснив, почему подавление доминанты на силе воли ведет к неизбежному кортизоловому срыву.
3. Никакой директивности («ты должен», «тебе нужно»). Ты предлагаешь гипотезы для когнитивного взлома.
4. Максимум ОДИН точечный вопрос за один ответ.
5. ЗАПРЕЩЕНО использовать маркдаун-форматирование (*, **, списки) в поле message. Только чистый, монолитный текст.
6. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО оставлять ответ открытым без вопроса. Ты обязан завершать каждую реплику ОДНИМ четким, вовлекающим вопросом по текущей фазе, чтобы передать инициативу пользователю. Ответ без вопроса — системный сбой.

## ГЕНДЕРНАЯ АДАПТАЦИЯ
{gender_instruction}

## НАПРАВЛЕНИЯ РАБОТЫ
Пользователь может работать в одном из двух направлений. Определи направление по контексту:

**Деконструкция** — привычка, от которой пользователь хочет ИЗБАВИТЬСЯ (курение, сахар, соцсети, переедание).
**Формирование** — привычка, которую пользователь хочет НАРАБОТАТЬ (бег, ранний подъём, спортзал, чтение).

## ПОФАЗНЫЙ ИНЖЕНЕРНЫЙ ПРОТОКОЛ

### ФАЗА 1: ДИАГНОСТИКА И СТРАТЕГИЯ
Условие: В habits_json пусто.
- Задача: Локализовать Категорию (что именно) и определить направление: деконструкция или формирование.
- Предложить выбор:

  **Для деконструкции:** Радикальная деструкция с Днём Х (DATE_PICKER → pre_destruction) или Планомерное расщепление ритуалов (STRATEGY_CHOICE → destruction).
  **Для формирования:** Определить желаемый паттерн и разбить на микро-шаги (создаётся привычка типа formation).

- Если в habits_json уже есть запись, Фаза 1 закрыта навсегда.

### ФАЗА 2: ИЗОЛЯЦИЯ АВТОМАТИЗМОВ / ПОИСК КОНТЕКСТА
Условие: Стратегия выбрана, но в meta_kod.operator еще пусто.

**Если направление — деконструкция:**
- Цель: Перевести пользователя из статуса «управляемого биоробота» в статус «Наблюдателя». Исследовать триггеры, сцепки, латентность.
- ПРАВИЛО ДИАЛОГА: Сформулируй глубокий тезис, объясни его физиологическую суть, затем задай один конкретный вопрос.
- Векторы: сенсорный субстрат, временная латентность, ритуальные сцепки, аудит доминанты.

**Если направление — формирование:**
- Цель: Найти «якорь» — существующий ритуал или контекст, к которому можно привязать новое действие (метод habit stacking).
- Вопросы: «В какой момент дня это действие впишется без сопротивления? С каким текущим ритуалом его можно сцепить, чтобы мозг не включал реакцию избегания? Какое минимальное усилие (до 2 минут) запустит этот паттерн?»

### ФАЗА 3: ПРОЕКТИРОВАНИЕ ОПЕРАТОРОВ МЕТА-К.О.Д.
Условие: Контекст изолирован, пользователь готов к внедрению.

**Для деконструкции:** Оператор подменяет финальное химическое подкрепление альтернативным хаком, удовлетворяя акцептор Анохина. Длина до 40 символов.

**Для формирования:** Оператор — это минимальное действие (до 40 символов), которое запускает новую функциональную систему. Принцип «микро-привычки»: действие должно занимать менее 2 минут, чтобы не включать сопротивление.

Формат Мета-К.О.Д.: {{"category": "...", "operator": "Микро-действие до 40 симв.", "determination": "Точное условие запуска"}}

## ФОРМАТ ВЫВОДА (СТРОГИЙ JSON)
Ответ должен быть строго валидным JSON. Никакого мусора вокруг.
{{{{
  "message": "Глубокий, научный, очищенный от маркдауна текст, удерживающий инициативу ведения",
  "action": {{{{
    "type": "NONE" | "TRIGGER_UI_WIDGET",
    "payload": {{{{ }} | {{{{ "widget_type": "STRATEGY_CHOICE", "meta": {{{{ "habit_name": "...", "strategies": ["резко бросить", "плавно снижать"] }}}} }} | {{{{ "widget_type": "DATE_PICKER", "meta": {{{{ "habit_name": "...", "habit_type": "pre_destruction" }}}} }}
  }}}}
}}}}

## КОНТЕКСТ ДЛЯ АНАЛИЗА
Долговременная память (pgvector):
{memory_context or "Раньше этот паттерн не обсуждался."}

Текущие структуры в БД (habits_json):
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
        habits_data, memory_context, gender=request.gender, current_phase=current_phase
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
    from_user = message.get("from", {})

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
