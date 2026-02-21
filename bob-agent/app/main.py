from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.db.database import init_db_engine
from app.services.bridge_service import bridge

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bridge.startup()
    await init_db_engine()
    # M7: app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    logger.info("bob_agent_started")
    yield
    await bridge.shutdown()
    # M7: await app.state.arq_pool.close()
    logger.info("bob_agent_stopped")


app = FastAPI(title="Bob Agent", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}
