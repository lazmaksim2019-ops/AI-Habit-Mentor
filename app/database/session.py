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
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await conn.run_sync(Base.metadata.create_all)

        # Migration: id INTEGER → UUID
        # Check if id is still integer
        result = await conn.execute(text(
            "SELECT data_type FROM information_schema.columns WHERE table_name='user_habits' AND column_name='id'"
        ))
        row = result.fetchone()
        if row and row[0] == 'integer':
            logger.info("Migrating user_habits.id from INTEGER to UUID...")
            await conn.execute(text("ALTER TABLE user_habits DROP COLUMN IF EXISTS id CASCADE"))
            await conn.execute(text("ALTER TABLE user_habits ADD COLUMN id UUID PRIMARY KEY DEFAULT gen_random_uuid()"))
            logger.info("user_habits.id migrated to UUID")

        # Safe migration for new columns
        for col, col_type in [
            ("target_date", "TIMESTAMPTZ"),
            ("status", "VARCHAR(20) NOT NULL DEFAULT 'active'"),
            ("type", "VARCHAR(20) NOT NULL DEFAULT 'pre_destruction'"),
            ("meta_kod", "JSONB DEFAULT '{}'::jsonb"),
            ("logs", "JSONB DEFAULT '[]'::jsonb"),
            ("name", "VARCHAR(255)"),
            ("created_at", "TIMESTAMPTZ DEFAULT now()"),
        ]:
            await conn.execute(text(f"ALTER TABLE user_habits ADD COLUMN IF NOT EXISTS {col} {col_type}"))

        # Migrate title → name and set NOT NULL, then drop old title
        await conn.execute(text("UPDATE user_habits SET name = title WHERE name IS NULL AND title IS NOT NULL"))
        await conn.execute(text("ALTER TABLE user_habits ALTER COLUMN name SET NOT NULL"))
        await conn.execute(text("ALTER TABLE user_habits DROP COLUMN IF EXISTS title"))
