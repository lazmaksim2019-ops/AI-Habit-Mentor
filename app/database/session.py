import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

logger = logging.getLogger(__name__)

_engine = None
_async_session_maker = None


def get_engine():
    global _engine
    if _engine is not None:
        return _engine

    _engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"server_settings": {"search_path": "public"}},
    )
    return _engine


def get_session_maker():
    global _async_session_maker
    if _async_session_maker is None:
        _async_session_maker = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _async_session_maker


async def get_async_session():
    maker = get_session_maker()
    async with maker() as session:
        yield session


async def init_db():
    from app.database.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # Safe migrations for Neon.tech
        await conn.execute(text(
            "ALTER TABLE user_habits ADD COLUMN IF NOT EXISTS target_date TIMESTAMPTZ"
        ))
        await conn.execute(text(
            "ALTER TABLE user_habits ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'"
        ))
        await conn.execute(text(
            "ALTER TABLE user_habits ADD COLUMN IF NOT EXISTS type VARCHAR(20) NOT NULL DEFAULT 'pre_destruction'"
        ))
        await conn.execute(text(
            "ALTER TABLE user_habits ADD COLUMN IF NOT EXISTS meta_kod JSONB DEFAULT '{}'::jsonb"
        ))
        await conn.execute(text(
            "ALTER TABLE user_habits ADD COLUMN IF NOT EXISTS logs JSONB DEFAULT '[]'::jsonb"
        ))
        await conn.execute(text(
            "ALTER TABLE user_habits ADD COLUMN IF NOT EXISTS name VARCHAR(255)"
        ))
        await conn.execute(text(
            "ALTER TABLE user_habits ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()"
        ))
        # Migrate title -> name if name is null
        await conn.execute(text(
            "UPDATE user_habits SET name = title WHERE name IS NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE user_habits ALTER COLUMN name SET NOT NULL"
        ))
