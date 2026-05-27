# Bot Behavior Flow — Neuro-Adaptive AI Habit Mentor

## 1. Входящий запрос: `POST /api/chat`

**Файл:** `app/api/endpoints.py:92-127`

Принимает `{ "telegram_id": int, "message": str }`.

---

## 2. Поиск / создание анонимного UUID

**Файл:** `app/api/endpoints.py:21-34` — `_get_or_create_user()`

- Ищет `UserLink` по `telegram_id` в БД
- Если найден — возвращает существующий `user_uuid`
- Если нет — генерирует `uuid.uuid4()`, сохраняет связку `telegram_id ↔ UUID` в таблицу `user_links`
- **В ИИ-контур передаётся только UUID, никогда telegram_id**

---

## 3. Анонимизация сообщения (ФЗ-152)

**Файл:** `app/services/anonymizer.py` — `anonymize_text()`

Входящий `message` проходит через регулярные выражения:

| Паттерн | Замена |
|---|---|
| «Меня зовут …», «Я …», «Моё имя …» | `[NAME]` |
| Телефоны (все форматы РФ: +7, 8, 7XXXXXXXXXX) | `[PHONE]` |
| Email-адреса | `[EMAIL]` |
| URL, t.me/..., @username, linkedin.com/in/... | `[LINK]` |

Результат: **очищенный текст без персональных данных**.

---

## 4. Генерация эмбеддинга

**Файл:** `app/services/ai/gemini.py:27-45` — `get_embedding()`

- Отправляет очищенный текст в `text-embedding-004` (768d) через httpx
- Возвращает `List[float]` — векторное представление сообщения
- При ошибке → `[]` (поиск памяти пропускается, но приложение не падает)

---

## 5. Поиск релевантных воспоминаний (RAG)

**Файл:** `app/database/repository.py:10-38` — `get_relevant_memory()`

- SQL-запрос к `user_vector_memory`:
  ```sql
  SELECT content_text
  FROM user_vector_memory
  WHERE user_uuid = :user_uuid
  ORDER BY embedding_vector <=> :embedding::vector
  LIMIT 3
  ```
- Оператор `<=>` — косинусное расстояние pgvector
- Результат: топ-3 текстовых фрагмента прошлых диалогов, склеенные в одну строку

---

## 6. Загрузка привычек пользователя

**Файл:** `app/api/endpoints.py:37-49` — `_get_user_habits_context()`

- `SELECT * FROM user_habits WHERE user_uuid = :uuid`
- Форматирует в человекочитаемый список:
  ```
  Привычки пользователя:
  - Зарядка [здоровье] — выполнена
  - Чтение [развитие] — не выполнена
  ```

---

## 7. Сборка system prompt

**Файл:** `app/api/endpoints.py:78-89` — `_build_system_prompt()`

```
Ты — Нейро-адаптивный ИИ-ментор привычек. ...
[привычки пользователя]
Контекст из прошлых диалогов:
[воспоминания RAG]
Будь поддерживающим, но честным. Отвечай на русском кратко и по делу.
Не запрашивай персональные данные пользователя.
```

---

## 8. Генерация ответа AI

**Файл:** `app/services/ai/gemini.py:47-79` — `generate_response()`

- Отправляет `system_instruction + history + current_message` в `gemini-3.1-flash-lite`
- Через httpx, с поддержкой прокси (для РФ)
- Возвращает текст ответа
- При ошибке → `"Извините, сервис временно недоступен..."`

---

## 9. Сохранение в долгосрочную память (фоновая задача)

**Файл:** `app/api/endpoints.py:52-75` — `_save_memory_background()`

Выполняется асинхронно через `BackgroundTasks`, **не блокирует ответ пользователю**:

1. Склеивает `"Вопрос: {cleaned_msg}\nОтвет: {ai_reply}"`
2. Генерирует эмбеддинг текста через `text-embedding-004`
3. Сохраняет `(user_uuid, embedding_vector, content_text)` в `user_vector_memory`

---

## 10. Ответ пользователю

```json
{ "reply": "..." }
```

---

## Вспомогательные ручки

| Endpoint | Файл | Назначение |
|---|---|---|
| `POST /api/habits/log` | `endpoints.py:130-158` | Создание/отметка привычки |
| `GET /health` | `main.py:41-43` | Healthcheck |

## Точка входа сервера

**Файл:** `main.py`

- FastAPI с CORS, global error handler
- `on_startup` → `init_db()` (создание таблиц)
- `on_shutdown` → `engine.dispose()`
- Uvicorn на `0.0.0.0:8000`
