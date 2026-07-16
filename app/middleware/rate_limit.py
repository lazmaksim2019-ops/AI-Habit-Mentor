from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)


def setup_rate_limiter(app: FastAPI) -> None:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def get_rate_limit_key(request: Request) -> str:
    user_id = request.headers.get("X-Telegram-User-ID")
    if user_id:
        return f"user:{user_id}"
    return get_remote_address(request)
