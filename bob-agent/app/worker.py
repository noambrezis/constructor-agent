"""ARQ task queue worker.

Start with:
    arq app.worker.WorkerSettings

The worker shares the same Python package as the agent so it can import
graph.run_agent() directly — no HTTP round-trip needed.
"""

import structlog
from arq.connections import RedisSettings

from app.agent.graph import run_agent
from app.config import settings
from app.db.database import init_db_engine
from app.models.webhook import MessageBody
from app.services.bridge_service import bridge
from app.services.site_cache import site_cache

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


async def process_message(ctx: dict, body: dict) -> None:
    """Deserialise the webhook body dict and run the LangGraph agent."""
    message = MessageBody(**body)
    log = logger.bind(group_id=message.groupId, message_id=message.messageId)
    log.info("worker_processing_message")
    await run_agent(message)
    log.info("worker_done")


# ---------------------------------------------------------------------------
# Lifecycle hooks
# ---------------------------------------------------------------------------


async def startup(ctx: dict) -> None:
    """Initialise shared resources once when the worker process starts."""
    await init_db_engine()
    await bridge.startup()
    await site_cache.startup(settings.REDIS_URL)
    logger.info("worker_started")


async def shutdown(ctx: dict) -> None:
    """Gracefully close shared resources when the worker shuts down."""
    await bridge.shutdown()
    await site_cache.shutdown()
    logger.info("worker_stopped")


# ---------------------------------------------------------------------------
# Worker configuration
# ---------------------------------------------------------------------------


class WorkerSettings:
    functions = [process_message]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 10
    job_timeout = 300        # 5 minutes per job (covers slow LLM + tool calls)
    keep_result = 3600       # keep result in Redis for 1 hour
    max_tries = 3            # retry on unhandled exception
    retry_jobs = True
