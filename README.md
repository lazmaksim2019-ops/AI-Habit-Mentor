<p align="center">
  <div align="center">
    <a href="https://ai-habit-mentor.onrender.com/">
      <img src="https://img.shields.io/badge/🚀_Live_Demo-Open_App-4285F4?style=for-the-badge&logo=render&logoColor=white"/>
    </a>
    <img src="https://img.shields.io/badge/Status-Production%20Ready-success?style=for-the-badge"/>
    <img src="https://img.shields.io/badge/Python-3.11_%7C_3.12-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
    <img src="https://img.shields.io/badge/FastAPI-0.115-teal?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
    <img src="https://img.shields.io/badge/PostgreSQL-16-blue?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL" />
    <img src="https://img.shields.io/badge/pgvector-RAG-indigo?style=for-the-badge&logo=database" alt="pgvector" />
    <img src="https://img.shields.io/badge/Gemini-3.1_Flash_Lite-gold?style=for-the-badge&logo=googlebard&logoColor=white" alt="Gemini" />
    <a href="https://github.com/lazmaksim2019-ops/AI-Habit-Mentor/actions">
      <img src="https://img.shields.io/github/actions/workflow/status/lazmaksim2019-ops/AI-Habit-Mentor/ci.yml?branch=master&style=for-the-badge&logo=github&label=CI"/>
    </a>
    <a href="https://codecov.io/gh/lazmaksim2019-ops/AI-Habit-Mentor">
      <img src="https://img.shields.io/codecov/c/github/lazmaksim2019-ops/AI-Habit-Mentor?style=for-the-badge&logo=codecov&label=Coverage"/>
    </a>
    <img src="https://img.shields.io/badge/Ruff-passing-brightgreen?style=for-the-badge&logo=python" alt="Ruff" />
    <img src="https://img.shields.io/badge/mypy-strict-blue?style=for-the-badge&logo=python" alt="mypy" />
    <img src="https://img.shields.io/badge/tests-22_%2F_22-green?style=for-the-badge&logo=pytest" alt="Tests" />
    <img src="https://img.shields.io/badge/Telegram-Mini_App-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram" />
    <img src="https://img.shields.io/badge/Security-%D0%A4%D0%97--152_Compliant-success?style=for-the-badge&logo=shield" alt="Security" />
  </div>
</p>

<h1 align="center">🧠 Neuro-Adaptive AI Habit Mentor</h1>

<p align="center">
  <b>Архитектурно-ориентированный AI-ментор привычек</b><br/>
  Telegram Mini App (TMA) | FastAPI | PostgreSQL+pgvector | Gemini | Production-ready
</p>

<p align="center">
  <a href="https://ai-habit-mentor.onrender.com/"><b>🚀 Live Demo</b></a>
  ·
  <a href="https://t.me/aIhabitmentorbot"><b>🤖 Открыть в Telegram</b></a>
  ·
  <a href="https://github.com/lazmaksim2019-ops/AI-Habit-Mentor"><b>📦 GitHub</b></a>
</p>

---

## 📋 Содержание

- [Архитектура](#-архитектура)
- [Quality Gates](#-quality-gates)
- [API Reference](#-api-reference)
- [Инфраструктура](#-инфраструктура)
- [Безопасность](#-безопасность)
- [CI/CD Pipeline](#-cicd-pipeline)
- [Быстрый старт](#-быстрый-старт)
- [Стек технологий](#-стек-технологий)

---

## 🏗 Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                        Telegram Client                          │
│  ┌──────────────────┐   ┌───────────────────────────────────┐  │
│  │   Native TMA SDK  │   │   Bot @aIhabitmentorbot           │  │
│  │   (WebView)       │   │   (webhook → /api/v1/webhook)     │  │
│  └────────┬─────────┘   └────────┬──────────────────────────┘  │
└───────────┼──────────────────────┼──────────────────────────────┘
            │                      │
            ▼                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Server                           │
│                                                                 │
│  ┌─────────────┐   ┌──────────────┐   ┌────────────────────┐   │
│  │  CORS       │   │  Rate Limit  │   │  Prometheus        │   │
│  │  Middleware  │   │  (slowapi)   │   │  (/metrics)        │   │
│  └─────────────┘   └──────────────┘   └────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                  API Router (/api/v1)                     │  │
│  │  ┌──────────┐  ┌─────────────┐  ┌──────────────────┐   │  │
│  │  │ POST/chat│  │ GET/habits  │  │ POST/webhook     │   │  │
│  │  │ POST/    │  │ POST/       │  │ GET /diag        │   │  │
│  │  │ batch    │  │ log-trigger │  │                  │   │  │
│  │  └────┬─────┘  └──────┬──────┘  └────────┬─────────┘   │  │
│  └───────┼───────────────┼──────────────────┼──────────────┘  │
│          │               │                  │                 │
│          ▼               ▼                  ▼                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                     Business Logic                      │  │
│  │  ┌──────────┐  ┌──────────────┐  ┌──────────────────┐   │  │
│  │  │Anonymizer│  │Vector Memory │  │  Phase Detector  │   │  │
│  │  │ (ФЗ-152) │  │  (RAG)      │  │  (K-O-D)         │   │  │
│  │  └──────────┘  └──────┬───────┘  └──────────────────┘   │  │
│  └──────────┬────────────┼───────────────────────────────────┘  │
│             │            │                                      │
│             ▼            ▼                                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              AI Provider (Abstraction)                    │  │
│  │  ┌────────────────────────────────────────────────────┐  │  │
│  │  │           BaseAIProvider (ABC)                     │  │  │
│  │  │     ┌──────────────────┐  ┌──────────────────┐    │  │  │
│  │  │     │ GeminiProvider   │  │ YandexGPTProvider│    │  │  │
│  │  │     │ (current)        │  │ (1-line swap)    │    │  │  │
│  │  │     └────────┬─────────┘  └──────────────────┘    │  │  │
│  │  └──────────────┼────────────────────────────────────┘  │  │
│  └─────────────────┼────────────────────────────────────────┘  │
│                    │                                           │
│                    ▼                                           │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  PostgreSQL + pgvector                                    │  │
│  │  ┌────────────┐  ┌──────────────┐  ┌──────────────────┐  │  │
│  │  │ user_links │  │ user_habits  │  │user_vector_memory│  │  │
│  │  │ (UUID↔TG)  │  │ (K-O-D data) │  │ (768-dim vec)    │  │  │
│  │  └────────────┘  └──────────────┘  └──────────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Ключевые архитектурные решения

| Решение | Описание |
|---------|----------|
| **Абстрактный AI-провайдер** | `BaseAIProvider` (ABC) позволяет заменить Gemini на YandexGPT одной строкой в конфиге — Enterprise-ready |
| **Vector RAG (pgvector)** | 768-мерные эмбеддинги + косинусное сходство → Top-3 релевантных воспоминаний подмешиваются в системный промпт |
| **Фазовый автомат** | 3 фазы протокола Мета-К.О.Д.: диагностика → изоляция триггеров → операторы. Детекция на бэкенде |
| **Anonymization Layer** | Zero-Trust к внешним API: все PII маскируются regex до передачи в Gemini |
| **Background Tasks** | Сохранение векторной памяти асинхронно, не блокируя ответ пользователю |

---

## 🎯 Quality Gates

### Тесты — 22/22 (100%) ✅

```bash
make test        # или: pytest -v --tb=short
```

| Категория | Тестов | Покрытие |
|-----------|--------|----------|
| Health & Metrics | 2 | ✅ |
| Chat Endpoint | 5 | ✅ |
| Habits Endpoints | 4 | ✅ |
| Diagnostic | 1 | ✅ |
| Anonymizer (ФЗ-152) | 7 | ✅ |
| Rate Limiting | 1 | ✅ |
| Main App | 4 | ✅ |

### Линтинг — Ruff (0 errors) ✅

```bash
make lint        # ruff check .
make format      # ruff format .
```

- Правила: E, F, B, I, N, UP, C4
- `line-length = 120`
- Автоматическое форматирование

### Типизация — mypy (strict) ✅

```bash
make typecheck   # mypy app/
```

- `strict = true`
- `no_implicit_optional = true`
- Third-party stubs для FastAPI, SQLAlchemy, httpx

### CI/CD Pipeline

```bash
make ci          # lint → typecheck → test
```

Три джобы в GitHub Actions:

1. **Lint & Typecheck** (ubuntu-latest, Python 3.11) — Ruff + mypy
2. **Test** (с pgvector/pg16 в service container) — Alembic migrations → pytest
3. **Build** (Docker) — зависит от lint + test

---

## 📡 API Reference

### `POST /api/v1/chat`
Основная точка входа AI-ментора.

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "telegram_id": 123456789,
    "message": "Хочу бросить курить",
    "gender": "male",
    "history": [],
    "phase": 1
  }'
```

### `GET /api/v1/habits`
Получить привычки пользователя.

```bash
curl "http://localhost:8000/api/v1/habits?telegram_id=123456789"
```

### `POST /api/v1/habits/batch-create`
Пакетное создание привычек (до 20).

```bash
curl -X POST http://localhost:8000/api/v1/habits/batch-create \
  -H "Content-Type: application/json" \
  -d '{
    "telegram_id": 123456789,
    "habits": [{"name": "Курение", "category": "health", "type": "destruction"}]
  }'
```

### `POST /api/v1/webhook`
Telegram Bot webhook (используется @aIhabitmentorbot).

```bash
# Автоматически регистрируется при старте через setWebhook
# POST https://api.telegram.org/bot<TOKEN>/setWebhook?url=<PUBLIC_URL>/api/v1/webhook
```

### `GET /api/v1/diag`
Диагностика подключения к Gemini API.

### `GET /health`
Health check.

### `GET /metrics`
Prometheus метрики.

Полная документация: `http://localhost:8000/docs` (Swagger)

---

## 🚀 Инфраструктура

### Локальная разработка

```bash
make install     # pip install -r requirements.txt
make run         # uvicorn main:app --reload
make migrate     # alembic upgrade head
```

### Docker

```bash
make docker-build    # docker build -t ai-habit-mentor .
make docker-run      # docker run -p 8000:8000 --env-file .env ai-habit-mentor
```

### Deploy (Render.com)

Конфиг в `render.yaml`:
- **Service type:** Docker
- **Plan:** Free
- **Health check:** `/health`
- **Auto-deploy:** включён
- **Env vars:** DATABASE_URL, GEMINI_API_KEY, TELEGRAM_BOT_TOKEN (все через Render dashboard)

---

## 🔒 Безопасность (ФЗ-152 Compliance)

Проект спроектирован по архитектуре **Zero-Trust к внешним API**:

1. **Anonymization Layer** — асинхронный модуль маскирует:
   - Имена → `[NAME]`
   - Телефоны → `[PHONE]`
   - Email → `[EMAIL]`
   - Ссылки → `[LINK]`
   - Паспорт, СНИЛС, ИНН, банковские карты, IP, адреса

2. **UUID-изоляция** — `telegram_id` → UUID маппинг в изолированной таблице `user_links`. Gemini видит только UUID

3. **Согласие пользователя** — экран согласия на обработку ПД при первом запуске (ФЗ-152)

4. **Rate Limiting** — slowapi с идентификацией по X-Telegram-User-ID

---

## 🛠 Стек технологий

| Категория | Технология | Версия |
|-----------|-----------|--------|
| **Язык** | Python | 3.11+ |
| **Фреймворк** | FastAPI | 0.115 |
| **База данных** | PostgreSQL + pgvector | 16 |
| **ORM** | SQLAlchemy | 2.0 (async) |
| **AI** | Google Gemini | 3.1 Flash Lite |
| **Прокси** | SOCKS5 (для Gemini в РФ) | — |
| **Фронтенд** | Tailwind CSS v4 + Marked.js | SPA |
| **Линтер** | Ruff | — |
| **Типизация** | mypy | strict |
| **Тесты** | pytest + pytest-asyncio | 22 ✅ |
| **CI** | GitHub Actions | 3 джобы |
| **Деплой** | Docker → Render.com | — |
| **Мониторинг** | Prometheus + slowapi | — |
| **Миграции** | Alembic | — |

---

## 📦 Структура проекта

```
├── main.py                    # FastAPI entry point + lifespan
├── Makefile                   # CLI-инструментарий
├── Dockerfile                 # Docker image
├── render.yaml                # Render.com deploy config
├── pyproject.toml             # Project metadata + tool configs
├── ruff.toml                  # Ruff linter config
├── mypy.ini                   # mypy strict config
├── requirements.txt           # Python dependencies
├── .env.example               # Environment template
├── .github/workflows/ci.yml   # CI pipeline (3 jobs)
├── alembic/                   # Database migrations
├── app/
│   ├── core/config.py         # Pydantic settings
│   ├── api/
│   │   ├── endpoints.py       # All API endpoints
│   │   └── schemas.py         # Pydantic schemas
│   ├── database/
│   │   ├── models.py          # SQLAlchemy ORM
│   │   ├── session.py         # Async engine + factory
│   │   └── repository.py      # pgvector search
│   ├── services/
│   │   ├── anonymizer.py      # PII masking (ФЗ-152)
│   │   └── ai/
│   │       ├── base.py        # Abstract provider
│   │       └── gemini.py      # Gemini implementation
│   └── middleware/
│       └── rate_limit.py      # slowapi rate limiter
├── src/templates/index.html   # Telegram Mini App SPA
└── tests/
    ├── conftest.py            # Fixtures + global mocks
    ├── test_api.py            # 22 API tests
    └── test_main.py           # 4 main app tests
```

---

## Автор

**Александр Лазаренко** — Fullstack Developer (FastAPI + React + AI)

[![Telegram](https://img.shields.io/badge/Telegram-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/lazalex81)
[![GitHub](https://img.shields.io/badge/GitHub-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/lazmaksim2019-ops)

---

<p align="center">
  <sub>Built with ❤️ for Telegram Mini App ecosystem</sub><br/>
  <sub>© 2026 — Neuro-Adaptive AI Habit Mentor</sub><br/>
  <sub><i>«Система не меняет привычки — она перестраивает нейронные связи.»</i></sub>
</p>
