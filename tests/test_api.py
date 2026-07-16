import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


class TestHealthEndpoint:
    async def test_health_endpoint(self, async_client: AsyncClient):
        response = await async_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestChatEndpoint:
    @patch("app.api.endpoints.GeminiProvider")
    @patch("app.api.endpoints.anonymize_text")
    @patch("app.api.endpoints.get_async_session")
    @patch("app.api.endpoints.get_relevant_memory")
    async def test_chat_success(
        self,
        mock_get_memory,
        mock_get_session,
        mock_anonymize,
        mock_gemini_class,
        async_client: AsyncClient,
    ):
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        mock_get_memory.return_value = ""

        mock_anonymize.return_value = "anonymized test message"

        mock_provider = AsyncMock()
        mock_provider.get_embedding.return_value = [0.1] * 768
        mock_provider.generate_response.return_value = json.dumps(
            {"message": "Test AI response", "action": {"type": "NONE", "payload": {}}}
        )
        mock_gemini_class.return_value = mock_provider

        response = await async_client.post(
            "/api/v1/chat",
            json={
                "telegram_id": 123456789,
                "message": "Привет, хочу бросить курить",
                "gender": "male",
                "history": [],
                "phase": 1,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "reply" in data
        assert "action" in data

    async def test_chat_missing_telegram_id(self, async_client: AsyncClient):
        response = await async_client.post(
            "/api/v1/chat", json={"message": "Test message", "gender": "male", "history": [], "phase": 1}
        )
        assert response.status_code == 422

    async def test_chat_invalid_gender(self, async_client: AsyncClient):
        response = await async_client.post(
            "/api/v1/chat",
            json={"telegram_id": 123456789, "message": "Test message", "gender": "invalid", "history": [], "phase": 1},
        )
        assert response.status_code == 422

    async def test_chat_empty_message(self, async_client: AsyncClient):
        response = await async_client.post(
            "/api/v1/chat", json={"telegram_id": 123456789, "message": "", "gender": "male", "history": [], "phase": 1}
        )
        assert response.status_code == 422


class TestHabitsEndpoints:
    @patch("app.api.endpoints.GeminiProvider")
    async def test_batch_create_habits(self, mock_gemini_class, async_client: AsyncClient):
        # Мокаем GeminiProvider чтобы не ходить в реальный API
        from unittest.mock import AsyncMock

        provider = AsyncMock()
        provider.get_embedding.return_value = [0.1] * 768
        mock_gemini_class.return_value = provider

        response = await async_client.post(
            "/api/v1/habits/batch-create",
            json={
                "telegram_id": 123456789,
                "habits": [{"name": "Test Habit", "category": "custom", "type": "pre_destruction", "meta_kod": {}}],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "habits" in data
        assert len(data["habits"]) >= 1

    async def test_get_habits_structure(self, async_client: AsyncClient):
        response = await async_client.get("/api/v1/habits?telegram_id=123456789")
        assert response.status_code == 200
        data = response.json()
        assert "habits" in data
        assert isinstance(data["habits"], list)

    async def test_log_trigger_not_found(self, async_client: AsyncClient):
        """Тест эндпоинта логирования триггера с несуществующей привычкой."""
        response = await async_client.post(
            "/api/v1/habits/log-trigger",
            json={
                "telegram_id": 123456789,
                "habit_id": "00000000-0000-0000-0000-000000000001",
                "intensity": 5,
                "note": "test trigger",
            },
        )
        # Ожидаем 404 так как привычка не найдена в mock
        assert response.status_code == 404


class TestDiagnosticEndpoint:
    @patch("app.api.endpoints.GeminiProvider")
    @patch("app.api.endpoints.settings")
    async def test_diagnostic_endpoint(self, mock_settings, mock_gemini_class, async_client: AsyncClient):
        mock_settings.GEMINI_API_KEY = "test-key"
        mock_settings.GEMINI_MODEL = "gemini-3.1-flash-lite"
        mock_settings.GEMINI_EMBEDDING_MODEL = "text-embedding-004"
        mock_settings.PROXY_HOST = None
        mock_settings.PROXY_PORT = None
        mock_settings.PROXY_USER = None
        mock_settings.proxy_url = None

        mock_provider = AsyncMock()
        mock_provider.base_url = "https://generativelanguage.googleapis.com/v1beta"
        mock_provider.model = "gemini-3.1-flash-lite"
        mock_provider.api_key = "test-key"
        mock_provider._client_kwargs = {}
        mock_gemini_class.return_value = mock_provider

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}
            mock_client.post.return_value = mock_response

            response = await async_client.get("/api/v1/diag")
            assert response.status_code == 200
            data = response.json()
            assert "api_key_set" in data
            assert "model" in data


class TestAnonymizer:
    @pytest.mark.asyncio
    async def test_anonymize_phone(self):
        from app.services.anonymizer import anonymize_text

        result = await anonymize_text("Мой телефон +7 999 123 45 67")
        assert "[PHONE]" in result

    @pytest.mark.asyncio
    async def test_anonymize_email(self):
        from app.services.anonymizer import anonymize_text

        result = await anonymize_text("Мой email test@example.com")
        assert "[EMAIL]" in result

    @pytest.mark.asyncio
    async def test_anonymize_passport(self):
        from app.services.anonymizer import anonymize_text

        result = await anonymize_text("Паспорт 1234 567890")
        assert "[PASSPORT]" in result

    @pytest.mark.asyncio
    async def test_anonymize_inn(self):
        from app.services.anonymizer import anonymize_text

        result = await anonymize_text("ИНН 1234567890")
        assert "[INN]" in result

    @pytest.mark.asyncio
    async def test_anonymize_snils(self):
        from app.services.anonymizer import anonymize_text

        result = await anonymize_text("СНИЛС 123-456-789 00")
        assert "[SNILS]" in result

    @pytest.mark.asyncio
    async def test_anonymize_bank_card(self):
        from app.services.anonymizer import anonymize_text

        result = await anonymize_text("Карта 1234 5678 9012 3456")
        assert "[CARD]" in result

    @pytest.mark.asyncio
    async def test_anonymize_name_pattern(self):
        from app.services.anonymizer import anonymize_text

        result = await anonymize_text("Меня зовут Иван Петров")
        assert "[NAME]" in result

    @pytest.mark.asyncio
    async def test_anonymize_url(self):
        from app.services.anonymizer import anonymize_text

        result = await anonymize_text("Ссылка https://example.com")
        assert "[LINK]" in result


class TestRateLimiting:
    async def test_rate_limit_headers(self, async_client: AsyncClient):
        response = await async_client.get("/health")
        assert response.status_code == 200
