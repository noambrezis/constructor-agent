# Shared fixtures — populated incrementally as modules are built.
#
# M2: test_db (real asyncpg session against docker-compose.test.yml Postgres)
# M3: mock_bridge (AsyncMock of all BridgeClient methods)
# M4: mock_llm (monkeypatches ChatOpenAI with deterministic stub)
# M6: test_client (httpx.AsyncClient against the FastAPI app)
#
# NOTE: We set required env vars here before any app module is imported, so
# that Settings() can be instantiated at collection time without a real .env.

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("SONIOX_API_KEY", "test-soniox-key")
os.environ.setdefault("PDFMONKEY_API_KEY", "test-pdfmonkey-key")
os.environ.setdefault("PDFMONKEY_TEMPLATE_ID", "test-template-id")
os.environ.setdefault("WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("BRIDGE_URL", "http://localhost:9999")
