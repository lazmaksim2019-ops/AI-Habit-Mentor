import logging
import os
import pathlib
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.endpoints import router as api_router
from app.core.config import settings
from app.database.session import get_engine, init_db
from app.middleware.rate_limit import setup_rate_limiter

BASE_DIR = pathlib.Path(__file__).parent

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database tables...")
    await init_db()
    logger.info("Database tables initialized")

    # Регистрируем Telegram webhook при старте
    if settings.TELEGRAM_BOT_TOKEN and settings.GEMINI_API_KEY:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # WEBHOOK_URL имеет приоритет, затем RENDER_EXTERNAL_URL (авто от Render)
                public_url = os.getenv("WEBHOOK_URL", "") or os.getenv("RENDER_EXTERNAL_URL", "")
                if not public_url:
                    public_url = f"http://localhost:{os.getenv('PORT', '8000')}"
                webhook_url = f"{public_url}/api/v1/webhook"
                resp = await client.post(
                    f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setWebhook",
                    json={"url": webhook_url},
                )
                if resp.status_code == 200:
                    logger.info("Telegram webhook set to %s", webhook_url)
                else:
                    logger.warning("Telegram webhook setup failed: %s", resp.text)
        except Exception as e:
            logger.warning("Failed to set Telegram webhook: %s", e)
    else:
        logger.info("TELEGRAM_BOT_TOKEN not set, skipping webhook registration")

    yield
    engine = get_engine()
    logger.info("Disposing database engine...")
    await engine.dispose()


app = FastAPI(
    title="Neuro-Adaptive AI Habit Mentor",
    version="1.0.0",
    description="Backend for Telegram Mini App — AI habit tracking with vector memory and FZ-152 compliance",
    lifespan=lifespan,
)

allowed_origins = [
    "https://web.telegram.org",
    "https://web.telegram.org/k/",
    "https://web.telegram.org/a/",
    "https://telegram.org",
]
if settings.DATABASE_URL and "localhost" in settings.DATABASE_URL:
    allowed_origins.append("*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

setup_rate_limiter(app)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.include_router(api_router, prefix="/api/v1")

templates_dir = BASE_DIR / "src" / "templates"
static_dir = BASE_DIR / "src" / "static"

templates_dir.mkdir(parents=True, exist_ok=True)
static_dir.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

INDEX_HTML_PATH = templates_dir / "index.html"
INDEX_HTML_CACHE: str | None = None


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
    request.state.request_id = request_id
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/", response_class=HTMLResponse)
@app.head("/", response_class=HTMLResponse)
async def index():
    global INDEX_HTML_CACHE
    if INDEX_HTML_CACHE is None:
        INDEX_HTML_CACHE = INDEX_HTML_PATH.read_text(encoding="utf-8")
    return HTMLResponse(content=INDEX_HTML_CACHE)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception("Unhandled exception [%s] on %s %s", request_id, request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": "Внутренняя ошибка сервера. Попробуйте позже."},
    )


@app.get("/health")
@app.head("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )
