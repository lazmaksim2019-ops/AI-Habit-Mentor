<p align="center">
  <div align="center">
    <img src="https://img.shields.io/badge/Python-3.11_/_3.12-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
    <img src="https://img.shields.io/badge/FastAPI-0.115-teal?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
    <img src="https://img.shields.io/badge/PostgreSQL-16-blue?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL" />
    <img src="https://img.shields.io/badge/pgvector-Semantic_RAG-indigo?style=for-the-badge&logo=database" alt="pgvector" />
    <img src="https://img.shields.io/badge/Gemini-3.1_Flash_Lite-gold?style=for-the-badge&logo=googlebard&logoColor=white" alt="Gemini" />
    <img src="https://img.shields.io/badge/Security-ФЗ--152_Compliant-success?style=for-the-badge&logo=shield" alt="Security" />
  </div>
</p>

<h1 align="center">🧠 Neuro-Adaptive AI Habit Mentor</h1>

<p align="center">
  <b>Премиальный AI-ментор привычек в формате Telegram Mini App (TMA). Научная когнитивная нейроинженерия на стыке мультимодальных LLM, теории функциональных систем П.К. Анохина и учения о доминанте А.А. Ухтомского.</b>
</p>

> **⚡ Ключевое отличие:** Никаких банальных советов в духе *"просто выпейте воды, когда хочется курить"*. Система деконструирует нежелательные нейронные связи (автоматизмы) и пошагово выстраивает новую доминанту поведения на основе строгого научного протокола.

---

## 📸 Скриншоты Интерфейса

<p align="center">
  <img src="assets/screenshots/110.png" width="22%" alt="Экран трекера" />
  <img src="assets/screenshots/111.png" width="22%" alt="Интерактивный чат" />
  <img src="assets/screenshots/112.png" width="22%" alt="Выбор стратегии" />
  <img src="assets/screenshots/113.png" width="22%" alt="Прогресс" />
</p>

---

## 🧬 Как это работает (Научная методология)

Система работает по протоколу **Мета-К.О.Д.** (автор Александр Лазаренко), проводя пользователя через детерминированный фазовый автомат на бэкенде:

1. **Деконструкция (Избавление от зависимости):** Плавное расщепление ритуала, изоляция триггера и замена химического подкрепления безопасным "оператором действия" (занимает $< 2$ минут).
2. **Формирование (Новый паттерн):** Метод *Habit Stacking* (привязка нового действия к существующему прочному доминантному ритуалу) с последующей стабилизацией функциональной системы мозга.

---

## ⚙️ Архитектурные и Инженерные решения

### 1. Семантическая память (Vector RAG) на pgvector
Для того чтобы ИИ помнил контекст общения сквозь недели сессий, используется векторная база данных **PostgreSQL + pgvector**.
* Все сообщения пользователя векторизуются в $768$-мерные эмбеддинги.
* Поиск релевантных воспоминаний (контекста) осуществляется на бэкенде по косинусному сходству:

$$\cos(\theta) = \frac{\mathbf{A} \cdot \mathbf{B}}{\|\mathbf{A}\| \|\mathbf{B}\|}$$

* Top-3 наиболее релевантных совпадений из прошлого опыта динамически подмешиваются в системный промпт LLM как "семантическая память".

### 2. Защита персональных данных (Полное соответствие ФЗ-152)
ИИ-решение спроектировано по архитектуре **Zero-Trust к внешним API** (модели Gemini). Никакие персональные данные (PII) не передаются за пределы контура РФ.

* **Асинхронный маскировщик (Anonymization Layer):** Модуль в `app/services/anonymizer.py` перехватывает сообщения и с помощью регулярных выражений и NLP маскирует конфиденциальные данные:
  * Имена ➔ `[NAME]`
  * Телефоны ➔ `[PHONE]`
  * Почта ➔ `[EMAIL]`
  * Ссылки ➔ `[LINK]`
* **UUIDv4-изоляция:** Связка `telegram_id` с UUID хранится в полностью изолированной таблице внутри РФ. Внешняя модель оперирует исключительно случайными UUIDv4-идентификаторами.

### 3. Фазовый автомат на бэкенде (State Machine)
Для предотвращения галлюцинаций и нарушений методологии, сервер строго контролирует фазу ведения пользователя. Логика бэкенда анализирует историю диалога и текущие привычки, динамически генерируя системные инструкции (System Instructions) под конкретную микро-задачу пользователя.

---

## 🛠️ Технологический стек

* **Бэкенд:** Python 3.14 (Async), FastAPI, Uvicorn, SQLAlchemy 2.0 Async, `asyncpg`.
* **База данных:** PostgreSQL 16 + расширение **pgvector** (семантический поиск).
* **ИИ-Ядро:** Google Gemini 3.1 Flash Lite (Эмбеддинги + Генерация) через SOCKS5-прокси.
* **Архитектурный паттерн:** Абстрактные провайдеры (`BaseAIProvider`). Перевод проекта на **YandexGPT** для Enterprise-деплоя в РФ осуществляется изменением одной строки конфигурации.
* **Фронтенд:** Single HTML SPA, Tailwind CSS v4, Marked.js (реальном времени стриминг Markdown).

---

## 📡 Спецификация API-эндпоинтов

| Метод | Эндпоинт | Описание | Входные данные |
|:---|:---|:---|:---|
| `POST` | `/api/chat` | Отправка сообщения ИИ (анонимизация, RAG, детекция фазы) | `ChatRequest` |
| `GET` | `/api/habits` | Получение списка привычек текущего пользователя | — |
| `POST` | `/api/habits/batch-create` | Пакетное создание привычек для трекинга (до 20 позиций) | `List[HabitCreate]` |
| `POST` | `/api/habits/log-trigger` | Логирование триггера срыва (оценка интенсивности от 1 до 10) | `TriggerLog` |

---

## 💻 Быстрый старт

```bash
# 1. Клонирование репозитория
git clone https://github.com/lazmaksim2019-ops/AI-Habit-Mentor.git
cd AI-Habit-Mentor

# 2. Создание и активация виртуального окружения
python -m venv .venv
source .venv/bin/activate # Для Linux/macOS
# .venv\Scripts\activate # Для Windows

# 3. Установка зависимостей
pip install -r requirements.txt

# 4. Настройка переменных среды
cp .env.example .env
# Укажите ваши ключи в файле .env (GEMINI_API_KEY, DATABASE_URL)

# 5. Запуск сервера разработки
python main.py
```

Swagger-документация API будет доступна по адресу: http://localhost:8000/docs.
