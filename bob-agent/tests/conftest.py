# Shared fixtures — populated incrementally as modules are built.
#
# M2: test_db (real asyncpg session against docker-compose.test.yml Postgres)
# M3: mock_bridge (AsyncMock of all BridgeClient methods)
# M4: mock_llm (monkeypatches ChatOpenAI with deterministic stub)
# M6: test_client (httpx.AsyncClient against the FastAPI app)
