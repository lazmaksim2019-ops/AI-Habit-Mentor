import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestMainApp:
    @pytest.mark.asyncio
    async def test_root_endpoint_returns_html(self, client):
        response = await client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_metrics_endpoint_exists(self, client):
        response = await client.get("/metrics")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_cors_headers(self, client):
        response = await client.options(
            "/api/v1/chat", headers={"Origin": "https://web.telegram.org", "Access-Control-Request-Method": "POST"}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_request_id_header(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert "x-request-id" in response.headers
