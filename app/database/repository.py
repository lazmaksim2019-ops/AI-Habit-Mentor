import logging
from typing import List
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_relevant_memory(
    session: AsyncSession,
    user_uuid: UUID,
    current_embedding: List[float],
    limit: int = 3,
) -> str:
    if not current_embedding:
        return ""

    embedding_str = "[" + ",".join(str(x) for x in current_embedding) + "]"

    query = text("""
        SELECT content_text
        FROM user_vector_memory
        WHERE user_uuid = :user_uuid
        ORDER BY embedding_vector <=> :embedding::vector
        LIMIT :limit
    """)

    try:
        result = await session.execute(
            query,
            {"user_uuid": user_uuid, "embedding": embedding_str, "limit": limit},
        )
        rows = result.fetchall()
        if not rows:
            return ""
        return "\n".join(row[0] for row in rows if row[0])
    except Exception as e:
        logger.error("Vector search failed for user %s: %s", user_uuid, e)
        return ""
