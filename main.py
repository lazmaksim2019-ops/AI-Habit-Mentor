import asyncio
import logging
import os
import pathlib
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = pathlib.Path(__file__).parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

from app.api.endpoints import router as api_router
from app.database.session import get_engine, init_db

asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database tables...")
    await init_db()
    logger.info("Database tables initialized")
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

templates_dir = BASE_DIR / "src" / "templates"
static_dir = BASE_DIR / "src" / "static"

templates_dir.mkdir(parents=True, exist_ok=True)
static_dir.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(templates_dir))
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "title": "Neuro-Adaptive AI Habit Mentor"},
        )
    except Exception as e:
        logger.exception("Template render failed, falling back to direct file read")
        html_path = templates_dir / "index.html"
        if html_path.exists():
            content = html_path.read_text(encoding="utf-8")
            content = content.replace("{{ title }}", "Neuro-Adaptive AI Habit Mentor")
            return HTMLResponse(content=content)
        raise


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": "Внутренняя ошибка сервера. Попробуйте позже."},
    )


@app.get("/health")
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
