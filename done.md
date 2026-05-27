# Neuro-Adaptive AI Habit Mentor — Done

## Созданный проект: Telegram Mini App Backend

### Структура (21 файл)

```
├── .env                        # Рабочие переменные (API-ключ, прокси)
├── .env.example                # Шаблон окружения
├── .gitignore
├── requirements.txt            # Зависимости
├── main.py                     # Точка входа FastAPI
├── rules.md                    # Правила проекта (vibe-coding framework)
└── app/
    ├── core/
    │   └── config.py           # Pydantic Settings (БД, Gemini, прокси)
    ├── database/
    │   ├── models.py           # ORM: UserLink, UserHabit, UserVectorMemory
    │   ├── session.py          # async engine + session factory + init_db
    │   └── repository.py       # get_relevant_memory() — pgvector cosine search
    ├── services/
    │   ├── anonymizer.py       # ФЗ-152: маскировка ПДн → [NAME], [PHONE], [EMAIL]
    │   └── ai/
    │       ├── base.py         # BaseAIProvider (abstract class)
    │       └── gemini.py       # GeminiProvider (httpx + прокси)
    └── api/
        ├── schemas.py          # Pydantic: ChatRequest/Response, HabitLogRequest/Response
        └── endpoints.py        # POST /api/chat, POST /api/habits/log, /health
```

---

### Что реализовано

**Шаг 1 — Окружение**
- `requirements.txt`: fastapi, uvicorn, pydantic, asyncpg, sqlalchemy[ext_asyncio], httpx, python-dotenv, pgvector, pydantic-settings
- `.env` / `.env.example` с переменными: `DATABASE_URL`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_EMBEDDING_MODEL`, прокси (`PROXY_HOST`, `PROXY_PORT`, `PROXY_USER`, `PROXY_PASS`)

**Шаг 2 — База данных (PostgreSQL + pgvector)**
- `UserLink` — таблица жёсткого сопоставления `telegram_id` ↔ `user_uuid` (UUID). Никаких имён/логинов.
- `UserHabit` — привычки пользователя (title, category, is_completed, updated_at)
- `UserVectorMemory` — векторная память с полем `embedding_vector: Vector(768)` (pgvector)
- Асинхронный SQLAlchemy 2.0 стиль (Mapped, mapped_column)

**Шаг 3 — Контур ФЗ-152 (анонимизация)**
- `anonymize_text()` отлавливает: имена/фамилии (по конструкциям «Меня зовут…», «Я …»), телефоны (все форматы РФ), email, ссылки, Telegram username, LinkedIn
- Замена на маркеры: `[NAME]`, `[PHONE]`, `[EMAIL]`, `[LINK]`

**Шаг 4 — AI модуль (абстракция + Gemini)**
- `BaseAIProvider` — абстрактный класс с `get_embedding()` и `generate_response()`
- `GeminiProvider` — реализация через httpx:
  - Эмбеддинги: `text-embedding-004` (768d)
  - Генерация: `gemini-3.1-flash-lite`
  - Прокси-поддержка (для РФ)
  - Все вызовы в `try/except` с логгированием. При отказе — `[]` для эмбеддинга, `FALLBACK_RESPONSE` для генерации. Приложение не падает.

**Шаг 5 — Векторный поиск (RAG)**
- `get_relevant_memory()`: SQL-запрос с `<=>` (pgvector cosine distance), TOP-3 воспоминания по конкретному `user_uuid`
- Асинхронный, с `try/except` и логированием

**Шаг 6 — API эндпоинты**
- `POST /api/chat`:
  1. Находит/создаёт анонимный `user_uuid` по `telegram_id`
  2. Анонимизирует сообщение
  3. Генерирует эмбеддинг
  4. Ищет релевантные воспоминания (RAG)
  5. Загружает привычки пользователя
  6. Собирает system prompt → отправляет в Gemini
  7. **BackgroundTasks**: после ответа сохраняет диалог в векторную память
  8. Возвращает JSON с ответом
- `POST /api/habits/log` — создать/отметить привычку
- `GET /health` — healthcheck

**Шаг 7 — Точка входа**
- `main.py`: CORS (разрешает всё), глобальный error handler (500 → JSON), `startup` (создание таблиц), `shutdown` (dispose engine), uvicorn на `0.0.0.0:8000`

---

### Как запустить

```powershell
# 1. Установить зависимости
pip install -r requirements.txt

# 2. Настроить .env
# DATABASE_URL=postgresql+asyncpg://user:password@host:5432/habits_db

# 3. Убедись, что в PostgreSQL включено расширение pgvector:
#   CREATE EXTENSION vector;

# 4. Запуск
python main.py
```

Сервер стартует на `http://0.0.0.0:8000`. Swagger-документация: `http://localhost:8000/docs`.

---

### Pipeline запроса в `POST /api/chat`

```
Telegram → message + telegram_id
    │
    ▼
Найти user_uuid по telegram_id (UserLink) — создать если нет
    │
    ▼
anonymize_text(message) → очищенный текст без ПДн
    │
    ▼
GeminiProvider.get_embedding() → вектор (List[float])
    │
    ▼
get_relevant_memory() → TOP-3 воспоминания из UserVectorMemory (cosine <=>)
    │
    ▼
SELECT * FROM UserHabit → контекст привычек
    │
    ▼
system_prompt (системная инструкция + привычки + воспоминания) → Gemini generate
    │
    ▼
Background task: сохранить вопрос+ответ в UserVectorMemory (асинхронно, не блокирует ответ)
    │
    ▼
JSON { "reply": "..." } → Telegram
```

### Ключевые архитектурные решения

- **Полностью асинхронный стек**: FastAPI + asyncpg + async SQLAlchemy + httpx
- **ФЗ-152**: ПДн маскируются до попадания в ИИ-контур. В БД — только UUIDv4, никаких телефонов/имён
- **Error isolation**: каждый внешний вызов обёрнут в `try/except` с `logging`. Ни один сбой (эмбеддинг, генерация, БД) не роняет приложение
- **Паттерн Strategy для AI**: `BaseAIProvider` → `GeminiProvider`. Можно добавить `YandexCloudProvider` без изменения эндпоинтов
- **RAG (Retrieval-Augmented Generation)**: косинусный поиск по pgvector, top-3 воспоминания подмешиваются в контекст
- **Прокси для РФ**: httpx-клиент настраивается через переменные `PROXY_*` в `.env`
