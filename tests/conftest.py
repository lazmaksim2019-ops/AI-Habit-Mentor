from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Сначала импортируем модуль session, потом патрим его через patch.object
import app.database.session as session_mod
import main as main_mod

session_mod.init_db = AsyncMock()  # type: ignore[assignment]

# get_engine возвращает заглушку, dispose — no-op
_mock_engine = AsyncMock()
_mock_engine.dispose = AsyncMock()

session_mod.get_engine = MagicMock(return_value=_mock_engine)
session_mod.create_async_engine = MagicMock(return_value=_mock_engine)
main_mod.get_engine = MagicMock(return_value=_mock_engine)
main_mod.init_db = AsyncMock()  # type: ignore[assignment]


@asynccontextmanager
async def _async_nullcontext():
    yield


from httpx import ASGITransport, AsyncClient  # noqa: E402

# Патчим ссылки в endpoints модуле
import app.api.endpoints as endpoints_mod  # noqa: E402
from main import app  # noqa: E402

_session = AsyncMock()


def _execute_side_effect(*args, **kwargs):
    sql = str(args[0]).lower() if args else ""
    if "user_links" in sql:
        res = MagicMock()
        res.scalar_one_or_none.return_value = None
        return res
    # Для всех остальных запросов — пустой результат
    res = MagicMock()
    res.scalar_one_or_none.return_value = None
    res.scalars.return_value.all.return_value = []
    res.scalars.return_value.first.return_value = None
    return res


_session.execute.side_effect = _execute_side_effect
_session.commit = AsyncMock()
_session.refresh = AsyncMock()


async def _mock_get_async_session():
    yield _session


# FastAPI dependency override — это перехватывает Depends(get_async_session)
app.dependency_overrides[session_mod.get_async_session] = _mock_get_async_session


@asynccontextmanager
async def _null_session():
    yield _session


endpoints_mod.get_session_maker = lambda: _null_session  # type: ignore[assignment]


async def _null_save_memory(*args, **kwargs):
    return None


endpoints_mod._save_memory_background = _null_save_memory  # type: ignore[assignment]

# Отключаем lifespan для тестов
app.router.lifespan_context = lambda app: _async_nullcontext()  # type: ignore[assignment]


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _reset_db_engine_state():
    session_mod._engine = None
    session_mod._async_session_maker = None
    yield
    session_mod._engine = None
    session_mod._async_session_maker = None


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_gemini_provider():
    with patch("app.api.endpoints.GeminiProvider") as mock:
        provider_instance = AsyncMock()
        provider_instance.get_embedding.return_value = [0.1] * 768
        provider_instance.generate_response.return_value = (
            '{"message": "Test response", "action": {"type": "NONE", "payload": {}}}'
        )
        mock.return_value = provider_instance
        yield mock


@pytest.fixture
def mock_anonymizer():
    with patch("app.api.endpoints.anonymize_text") as mock:
        mock.return_value = "anonymized message"
        yield mock


@pytest.fixture
def mock_db_session():
    with patch("app.api.endpoints.get_async_session") as mock:
        session = AsyncMock()
        mock.return_value = session
        yield session
