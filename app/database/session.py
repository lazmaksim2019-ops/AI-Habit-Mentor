import logging
import socket
from urllib.parse import urlparse

import dns.resolver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

logger = logging.getLogger(__name__)

_FALLBACK_NS = ["8.8.8.8", "1.1.1.1"]


def _resolve_hostname(url: str) -> str:
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return url

    try:
        addrs = socket.getaddrinfo(hostname, parsed.port or 5432, socket.AF_INET)
        if addrs:
            ip = addrs[0][4][0]
            logger.info("DNS resolved %s -> %s (system)", hostname, ip)
            return url.replace(parsed.netloc, parsed.netloc.replace(hostname, ip, 1), 1)
    except socket.gaierror:
        logger.warning("System DNS failed for %s, trying fallback DNS...", hostname)

    try:
        resolver = dns.resolver.Resolver()
        resolver.nameservers = _FALLBACK_NS
        answers = resolver.resolve(hostname, "A")
        ip = str(answers[0])
        logger.info("DNS resolved %s -> %s (fallback)", hostname, ip)
        return url.replace(parsed.netloc, parsed.netloc.replace(hostname, ip, 1), 1)
    except Exception as e:
        logger.error("Fallback DNS also failed for %s: %s", hostname, e)

    return url


def _build_engine():
    connect_args = {}
    url_lower = settings.DATABASE_URL.lower()
    if "supabase" in url_lower and "ssl=" not in url_lower:
        connect_args["ssl"] = True

    engine_url = _resolve_hostname(settings.DATABASE_URL)

    return create_async_engine(
        engine_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args=connect_args,
    )


engine = _build_engine()

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_async_session():
    async with async_session() as session:
        yield session


async def init_db():
    from app.database.models import Base

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
