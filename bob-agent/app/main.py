from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from fastapi import Depends, FastAPI, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import get_session, init_db_engine
from app.db.repositories import dedup_repo
from app.middleware.auth import verify_webhook_secret
from app.middleware.rate_limit import check_rate_limit
from app.models.webhook import WebhookPayload
from app.services.bridge_service import bridge

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bridge.startup()
    await init_db_engine()
    app.state.redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    # M7: app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    logger.info("bob_agent_started")
    yield
    await bridge.shutdown()
    await app.state.redis.aclose()
    # M7: await app.state.arq_pool.close()
    logger.info("bob_agent_stopped")


app = FastAPI(title="Bob Agent", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/agent")
async def handle_message(
    request: Request,
    payload: WebhookPayload,
    session: AsyncSession = Depends(get_session),
    x_webhook_secret: str | None = Header(None),
):
    # 1. Authenticate
    verify_webhook_secret(x_webhook_secret)

    body = payload.body
    log = logger.bind(group_id=body.groupId, message_id=body.messageId)

    # 2. Rate limit per group (Redis sliding window)
    await check_rate_limit(request, body.groupId)

    # 3. Deduplicate — return 200 immediately if already seen
    if await dedup_repo.is_already_processed(session, body.messageId):
        log.info("duplicate_message_skipped")
        return {"status": "duplicate"}

    # 4. Mark as processed before enqueue to prevent race on rapid Bridge retry
    await dedup_repo.mark_as_processed(session, body.messageId, body.groupId)
    await session.commit()

    # 5. Enqueue durable task (M7: ARQ worker)
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if arq_pool is not None:
        await arq_pool.enqueue_job("process_message", body.model_dump())
    else:
        log.warning("arq_pool_not_ready", note="message accepted but not queued — M7 pending")

    log.info("message_accepted")
    return {"status": "accepted"}
