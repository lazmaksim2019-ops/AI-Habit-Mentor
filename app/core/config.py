from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"
    GEMINI_EMBEDDING_MODEL: str = "text-embedding-004"
    TELEGRAM_BOT_TOKEN: str = ""
    PROXY_HOST: str | None = None
    PROXY_PORT: int | None = None
    PROXY_USER: str | None = None
    PROXY_PASS: str | None = None

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def proxy_url(self) -> str | None:
        if not self.PROXY_HOST or not self.PROXY_PORT:
            return None
        if self.PROXY_USER and self.PROXY_PASS:
            return f"http://{self.PROXY_USER}:{self.PROXY_PASS}@{self.PROXY_HOST}:{self.PROXY_PORT}"
        return f"http://{self.PROXY_HOST}:{self.PROXY_PORT}"


settings = Settings()
