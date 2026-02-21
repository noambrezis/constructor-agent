from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
from fastapi.testclient import TestClient

from app.main import app


def test_health():
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    with (
        patch("app.main.bridge.startup", new_callable=AsyncMock),
        patch("app.main.bridge.shutdown", new_callable=AsyncMock),
        patch("app.main.init_db_engine", new_callable=AsyncMock),
        patch("app.main.site_cache.startup", new_callable=AsyncMock),
        patch("app.main.site_cache.shutdown", new_callable=AsyncMock),
        patch(
            "app.main.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ),
        patch(
            "app.main.aioredis.from_url",
            return_value=fakeredis.aioredis.FakeRedis(decode_responses=True),
        ),
    ):
        with TestClient(app) as client:
            response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
