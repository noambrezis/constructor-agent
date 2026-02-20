from sqlalchemy import exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProcessedMessage


async def is_already_processed(session: AsyncSession, message_id: str) -> bool:
    """Return True if this message_id has already been processed."""
    result = await session.execute(
        select(exists().where(ProcessedMessage.message_id == message_id))
    )
    return bool(result.scalar())


async def mark_as_processed(
    session: AsyncSession, message_id: str, group_id: str
) -> None:
    """Insert a deduplication record. Silently ignores duplicate inserts."""
    await session.execute(
        text(
            "INSERT INTO processed_messages (message_id, group_id) "
            "VALUES (:message_id, :group_id) "
            "ON CONFLICT DO NOTHING"
        ),
        {"message_id": message_id, "group_id": group_id},
    )
    await session.flush()
