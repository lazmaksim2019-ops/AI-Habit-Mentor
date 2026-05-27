import logging
import socket
from urllib.parse import urlparse

import dns.resolver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

logger = logging.getLogger(__name__)

# Fallback IPs для Supabase pooler (AWS ELB — меняются редко)
_IP_FALLBACK = {
    "aws-0-eu-central-1.pooler.supabase.com": "18.198.145.223",
}


def _replace_host_with_ip(url: str, hostname: str, ip: str) -> str:
    old_netloc = urlparse(url).netloc
    new_netloc = old_netloc.replace(hostname, ip, 1)
    return url.replace(old_netloc, new_netloc, 1)


def _resolve_hostname(url: str) -> str:
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return url

    # 1 — system DNS (getaddrinfo)
    try:
        addrs = socket.getaddrinfo(hostname, parsed.port or 5432, socket.AF_INET)
        if addrs:
            ip = addrs[0][4][0]
            logger.info("DNS resolved %s -> %s (system)", hostname, ip)
            return _replace_host_with_ip(url, hostname, ip)
    except socket.gaierror:
        logger.warning("System DNS failed for %s", hostname)

    # 2 — raw UDP DNS via dnspython (port 53, может быть заблокирован)
    try:
        resolver = dns.resolver.Resolver()
        resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
        answers = resolver.resolve(hostname, "A")
        ip = str(answers[0])
        logger.info("DNS resolved %s -> %s (udp)", hostname, ip)
        return _replace_host_with_ip(url, hostname, ip)
    except Exception as e:
        logger.warning("UDP DNS failed for %s: %s", hostname, e)

    # 3 — hardcoded fallback (известные IP Supabase pooler)
    hardcoded = _IP_FALLBACK.get(hostname)
    if hardcoded:
        logger.info("DNS resolved %s -> %s (hardcoded)", hostname, hardcoded)
        return _replace_host_with_ip(url, hostname, hardcoded)

    logger.error("All DNS methods exhausted for %s", hostname)
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
