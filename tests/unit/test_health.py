from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "chathr-api"


def test_ready_degraded_does_not_expose_exception_class():
    """When a service is unreachable, /ready must not reveal exception class names."""
    with patch("asyncpg.connect", side_effect=ConnectionRefusedError("refused")), \
         patch("redis.asyncio.from_url") as mock_redis:
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(side_effect=ConnectionRefusedError("refused"))
        mock_client.aclose = AsyncMock()
        mock_redis.return_value = mock_client

        response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    for check_value in body["checks"].values():
        assert "ConnectionRefusedError" not in check_value
        assert "Exception" not in check_value
        assert check_value in ("ok", "error")
