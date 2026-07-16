.PHONY: install test lint format typecheck migrate run ci docker-build clean

# ─── Development ────────────────────────────────────────────

install: ## Установка зависимостей
	pip install -r requirements.txt
	pip install ruff mypy pytest pytest-asyncio httpx 2>/dev/null || true

test: ## Запуск тестов
	python -m pytest tests/ -v --tb=short

lint: ## Линтинг Ruff
	ruff check .

format: ## Форматирование кода
	ruff format .

typecheck: ## Проверка типов mypy
	mypy app/

migrate: ## Применение миграций БД
	alembic upgrade head

migrate-new: ## Создать новую миграцию (usage: make migrate-new msg="описание")
	alembic revision --autogenerate -m "$(msg)"

# ─── Run ────────────────────────────────────────────────────

run: ## Запуск dev-сервера
	uvicorn main:app --reload --host 0.0.0.0 --port 8000

# ─── Docker ─────────────────────────────────────────────────

docker-build: ## Сборка Docker-образа
	docker build -t ai-habit-mentor .

docker-run: ## Запуск в Docker
	docker run -p 8000:8000 --env-file .env ai-habit-mentor

# ─── CI / Quality ───────────────────────────────────────────

ci: lint typecheck test ## Полный CI-пайплайн (линтер + типы + тесты)

# ─── Maintenance ────────────────────────────────────────────

clean: ## Очистка кэша
	rm -rf __pycache__ .pytest_cache .ruff_cache .mypy_cache
	rm -rf app/**/__pycache__ tests/**/__pycache__ 2>/dev/null || true
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

help: ## Показать все цели
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
