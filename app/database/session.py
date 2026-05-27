import logging
import socket
import sys
from urllib.parse import urlparse

import dns.resolver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

logger = logging.getLogger(__name__)

_IP_FALLBACK = {
    "aws-0-eu-central-1.pooler.supabase.com": "18.198.145.223",
}

_engine = None
_async_session_maker = None


def _replace_host_with_ip(url: str, hostname: str, ip: str) -> str:
    old_netloc = urlparse(url).netloc
    new_netloc = old_netloc.replace(hostname, ip, 1)
    return url.replace(old_netloc, new_netloc, 1)


def _resolve_hostname(url: str) -> str:
    parsed = urlparse(url)
    hostname = parsed.hostname
    print(f"[DNS-RESOLVE] Parsing URL, hostname={hostname}", file=sys.stderr)

    if not hostname:
        return url

    try:
        addrs = socket.getaddrinfo(hostname, parsed.port or 5432, socket.AF_INET)
        if addrs:
            ip = addrs[0][4][0]
            print(f"[DNS-RESOLVE] System DNS: {hostname} -> {ip}", file=sys.stderr)
            return _replace_host_with_ip(url, hostname, ip)
    except socket.gaierror:
        print(f"[DNS-RESOLVE] System DNS failed for {hostname}", file=sys.stderr)

    try:
        resolver = dns.resolver.Resolver()
        resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
        answers = resolver.resolve(hostname, "A")
        ip = str(answers[0])
        print(f"[DNS-RESOLVE] UDP DNS: {hostname} -> {ip}", file=sys.stderr)
        return _replace_host_with_ip(url, hostname, ip)
    except Exception as e:
        print(f"[DNS-RESOLVE] UDP DNS failed: {e}", file=sys.stderr)

    hardcoded = _IP_FALLBACK.get(hostname)
    if hardcoded:
        print(f"[DNS-RESOLVE] Hardcoded: {hostname} -> {hardcoded}", file=sys.stderr)
        return _replace_host_with_ip(url, hostname, hardcoded)

    print(f"[DNS-RESOLVE] ALL METHODS FAILED for {hostname}", file=sys.stderr)
    return url


def _sanitize_url(url: str) -> str:
    """Remove query params that asyncpg cannot handle (e.g. server_settings as string)."""
    if "?" not in url:
        return url
    base, query = url.split("?", 1)
    safe = [p for p in query.split("&") if not p.lower().startswith("server_settings=")]
    if not safe:
        return base
    return f"{base}?{'&'.join(safe)}"


def get_engine():
    global _engine
    if _engine is not None:
        return _engine

    connect_args = {}
    url_lower = settings.DATABASE_URL.lower()
    if "supabase" in url_lower and "ssl=" not in url_lower:
        connect_args["ssl"] = True

    engine_url = _sanitize_url(_resolve_hostname(settings.DATABASE_URL))
    final_host = urlparse(engine_url).hostname
    print(f"[DNS-RESOLVE] Final engine host: {final_host}", file=sys.stderr)

    _engine = create_async_engine(
        engine_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args=connect_args,
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
