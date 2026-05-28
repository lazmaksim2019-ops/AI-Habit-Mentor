# Архитектура: Neuro-Adaptive AI Habit Mentor

## 1. Суть приложения

**Премиальный AI-трекер привычек** на базе методологии **K-O-D (Когнитивный Оператор Деконструкции)** — адаптация когнитивно-поведенческой терапии (CBT) для отказа от зависимостей (курение, сахар, соцсети и т.д.).

Пользователь общается с AI в чате, AI проводит его через **3 строгие фазы**:

1.  **Диагностика + выбор стратегии** — выявление привычки, выбор: резко бросить (с Днём Х) или плавно снижать
2.  **Изоляция автоматизмов** — анализ триггеров, контекста срыва, включение «наблюдателя»
3.  **Внедрение микро-привычек** — трекер действий до 40 символов

Фишки: инлайн-виджеты (DatePicker, StrategyChoice), логгер триггеров с оценкой интенсивности (1–10), векторная память (pgvector), единый SPA на чистом HTML/JS.

---

## 2. Почему пользователь будет платить

**Ежедневная ценность:**

- **AI-ментор 24/7** — не надо ждать психолога, AI всегда в кармане (Telegram Mini App)
- **Персонализация** — AI помнит всю историю диалога + семантически релевантные прошлые беседы (pgvector)
- **Пошаговое ведение** без давления, без мотивационного шума — научный инжиниринг, а не «просто брось»
- **Трекер с прогревом** — countdown до Дня Х, визуализация прогресса, streak (серии дней)
- **Конфиденциальность** — FZ-152 compliance, анонимизация `user_uuid`, нет привязки к личности

**Модель монетизации:**

- Подписка на AI-диалоги (бесплатно N сообщений/день, далее платно)
- Премиум: неограниченные диалоги, расширенная аналитика, экспорт прогресса

---

## 3. Архитектура

### Backend (FastAPI + PostgreSQL + pgvector)

```
main.py                          — точка входа, lifespan (init_db), CORS, /health
├── app/
│   ├── api/
│   │   ├── endpoints.py         — все API-роуты (chat, habits CRUD, logging)
│   │   └── schemas.py           — Pydantic-модели запросов/ответов
│   ├── core/
│   │   └── config.py            — настройки (Gemini API, БД, прокси)
│   ├── database/
│   │   ├── models.py            — SQLAlchemy: UserLink, UserHabit, UserVectorMemory
│   │   ├── session.py           — async engine, init_db(), миграции
│   │   └── repository.py        — get_relevant_memory() — pgvector similarity search
│   └── services/
│       └── ai/
│           ├── gemini.py        — GeminiProvider (embedding + generate)
│           └── base.py          — BaseAIProvider (abstract)
└── src/
    └── templates/
        └── index.html           — SPA (Tracker + AI Chat + Progress)
```

### Модели данных (PostgreSQL)

| Таблица | Назначение | Ключевые поля |
|---------|-----------|---------------|
| `user_links` | Анонимная привязка Telegram → UUID | `telegram_id` (BigInt, unique), `user_uuid` (PK) |
| `user_habits` | Привычки пользователя | `id` (UUID), `user_uuid` (FK), `name`, `type` (pre_destruction/destruction/stabilization), `meta_kod` (JSONB), `target_date`, `logs` (JSONB), `status` |
| `user_vector_memory` | Векторная память диалогов | `embedding_vector` (Vector(768)), `content_text` (Text), `user_uuid` (FK) |

### API endpoints

| Метод | Путь | Описание |
|-------|------|---------|
| POST | `/api/chat` | Отправить сообщение AI. Принимает `message`, `history[]`, `gender`. Возвращает JSON с `message` + `action` (виджет) |
| GET | `/api/habits` | Список привычек пользователя |
| POST | `/api/habits/batch-create` | Создать 1–20 привычек |
| POST | `/api/habits/set-target-date` | Установить День Х |
| POST | `/api/habits/log-trigger` | Лог триггера (интенсивность 1–10, заметка) |
| GET | `/api/diag` | Диагностика Gemini API |

---

## 4. Как прописано поведение AI

### 4a. System prompt (`endpoints.py:117-167`)

Главный файл: `app/api/endpoints.py`, функция `_build_system_prompt()`.

Структура промпта:

```
## I. ТОН И СТИЛЬ
- Партнёрство, недирективность (не приказывать, не давить)
- Простой язык (без «нейрохимический ландшафт»)
- Один шаг — один вопрос
- Грамматический род (male/female)

## II. СТРОГАЯ СТРУКТУРА ДИАЛОГА (СТЕЙТ-МАШИНА)
3 фазы, возврат ЗАПРЕЩЁН:
  ФАЗА 1: Диагностика + STRATEGY_CHOICE (только один раз!)
  ФАЗА 2: Изоляция автоматизмов (контекст срыва, триггеры)
  ФАЗА 3: Микро-привычки (трекер)

## III. ФОРМАТ ОТВЕТА (СТРОГИЙ JSON)
message + action.type (NONE | TRIGGER_UI_WIDGET)
  - STRATEGY_CHOICE: две кнопки выбора
  - DATE_PICKER: календарь (только если выбрал «резко»)

## IV. КОНТЕКСТ
- Последние сообщения (history из запроса)
- Векторная память (семантический поиск)
- Привычки пользователя (JSON)
```

### 4b. Gemini-провайдер (`app/services/ai/gemini.py`)

Класс `GeminiProvider`:

- **generate_response()**: получает `system_instruction`, `history[]` (маппинг: assistant→model, user→user), `current_message`. Шлёт POST на `models/{model}:generateContent`.
- **get_embedding()**: получает вектор текста через `models/{embedding_model}:embedContent`. Размерность 768 (под pgvector).
- Прокси-поддержка: httpx 0.28+ использует `proxy` (singular), старые — `proxies` (plural).
- Fallback: при любой ошибке возвращает `"Извините, сервис временно недоступен..."`.
- Модель: `gemini-3.1-flash-lite` (лёгкая, быстрая).

### 4c. Память (контекстная)

**Два уровня памяти:**

1.  **Краткосрочная** (`ChatRequest.history`) — фронтенд шлёт последние 4 сообщения (user + ai, parsed, без JSON-обёрток). Бекенд маппит роли и передаёт в Gemini.

2.  **Долгосрочная (векторная)** — `app/database/repository.py:get_relevant_memory()`:
    - Берёт embedding нового сообщения пользователя
    - Ищет top-3 семантически похожих записей из `user_vector_memory` через `<=>` (cosine distance)
    - Возвращает как plain text в system prompt

**Сохранение памяти:** После ответа AI фоново (`BackgroundTasks`) сохраняет пару вопрос+ответ как вектор в `user_vector_memory`.

### 4d. Фронтенд — парсинг AI-ответа (`index.html:1160-1214`)

Функция `parseAiReply()`:

1.  Ищет JSON в ` ```json ... ```` блоке
2.  Если не находит — пытается распарсить весь ответ как JSON
3.  Извлекает `message` + `action.type` + `action.payload.widget_type`
4.  Если `widget_type === "DATE_PICKER"` — генерирует HTML календаря
5.  Если `widget_type === "STRATEGY_CHOICE"` — генерирует две кнопки выбора
6.  Если JSON не распарсен — возвращает `{ message: reply, action: null, widget: null }`

**Защита от зацикливания AI** (`index.html:1145-1148`):

- После выбора стратегии устанавливается `state.strategyChosen = true`
- Если AI снова присылает `STRATEGY_CHOICE`, виджет **отбрасывается** на фронтенде
- `strategyChosen` сохраняется в localStorage

### 4e. Виджеты (рендеринг в чате)

**Strategy Choice** (`index.html:1194-1204`):

- Две кнопки: «Резко бросить» / «Плавно снижать»
- По клику: все кнопки блокируются, `strategyChosen = true`
- Если выбрал «резко» → показывается DatePicker
- Если выбрал «плавно» → создаётся привычка «Осознание: ...»
- Consumed widgets рендерятся с `disabled` и `opacity: 0.4`

**DatePicker** (`index.html:1187-1193`):

- Инлайн календарь в чате
- После подтверждения → `POST /api/habits/set-target-date`

**Trigger Logger** (модальное окно):

- Intensity slider (1–10)
- Note field
- `POST /api/habits/log-trigger`

---

## 5. Полный цикл запроса

```
Пользователь пишет сообщение
  → handleChatSend() [index.html:1127]
    → push user message in chatHistory
    → renderChat()
    → sendChatMessage(text) [POST /api/chat]
      → endpoint: chat() [endpoints.py:198]
        → _get_or_create_user() — UUID по telegram_id
        → anonymize_text() — фильтр PII
        → get_embedding() — вектор сообщения
        → get_relevant_memory() — top-3 похожих диалогов
        → _build_system_prompt() — промпт с контекстом, памятью, привычками
        → GeminiProvider.generate_response() — запрос к Gemini
        → _save_memory_background() — фон: сохранить QA-пару в векторную БД
        → return ChatResponse(reply)
    ← parseAiReply(reply) — JSON → message + widget
    → push ai message in chatHistory
    → renderChat() — рендер сообщений + привязка событий виджетов
```

---

## 6. Ключевые файлы

| Файл | Строк | Роль |
|------|-------|------|
| `app/api/endpoints.py` | 431 | System prompt, все API-роуты, логика чата |
| `app/services/ai/gemini.py` | 116 | Gemini API (generate + embedding), прокси |
| `app/database/repository.py` | 41 | pgvector similarity search |
| `app/database/session.py` | 82 | init_db(), миграции (INT→UUID) |
| `app/database/models.py` | 74 | SQLAlchemy ORM модели |
| `app/api/schemas.py` | 91 | Pydantic-схемы (ChatRequest, ChatResponse, HabitCreate) |
| `src/templates/index.html` | 1416 | SPA: трекер, чат, прогресс, виджеты |
| `app/core/config.py` | — | secrets: GEMINI_API_KEY, DATABASE_URL, PROXY |

---

## 7. Текущие проблемы и точки роста

- **AI зацикливается на STRATEGY_CHOICE** — частично пофикшено (строгая стейт-машина в промпте + фронтенд-защита), но требуется **явный `phase` field** в `ChatRequest` для однозначного контекста модели
- Нет ежедневного чекина (`POST /api/habits/log`) для `stabilization`-типа привычек
- Нет push-уведомлений через Telegram Bot API
- Нет метрик (DAU, retention, конверсия в подписку)
