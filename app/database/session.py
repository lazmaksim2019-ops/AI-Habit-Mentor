import json
import logging
import socket
from urllib.parse import urlparse

import dns.resolver
import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

logger = logging.getLogger(__name__)

_DOH_URL = "https://dns.google/resolve?name={name}&type=A"


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

    # 2 — raw DNS queries via dnspython (port 53 UDP)
    try:
        resolver = dns.resolver.Resolver()
        resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
        answers = resolver.resolve(hostname, "A")
        ip = str(answers[0])
        logger.info("DNS resolved %s -> %s (udp)", hostname, ip)
        return _replace_host_with_ip(url, hostname, ip)
    except Exception as e:
        logger.warning("UDP DNS failed for %s: %s", hostname, e)

    # 3 — DNS-over-HTTPS (port 443, не блокируется Render)
    try:
        resp = httpx.get(_DOH_URL.format(name=hostname), timeout=10.0)
        data = resp.json()
        for answer in data.get("Answer", []):
            if answer.get("type") == 1:
                ip = answer["data"]
                logger.info("DNS resolved %s -> %s (DoH)", hostname, ip)
                return _replace_host_with_ip(url, hostname, ip)
    except Exception as e:
        logger.error("DoH also failed for %s: %s", hostname, e)

    logger.error("All DNS methods failed for %s — connection will likely fail", hostname)
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
