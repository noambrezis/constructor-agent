from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.database import init_db_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # M3: await bridge.startup()
    await init_db_engine()
    # M6: app.state.redis = await aioredis.from_url(settings.REDIS_URL)
    # M7: app.state.arq_pool = await create_pool(...)
    yield
    # M3: await bridge.shutdown()
    # M6: await app.state.arq_pool.close()


app = FastAPI(title="Bob Agent", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}
