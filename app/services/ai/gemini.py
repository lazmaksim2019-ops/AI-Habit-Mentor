import hashlib
import json
import logging
import traceback
from collections import OrderedDict
from collections.abc import AsyncGenerator

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.services.ai.base import BaseAIProvider

logger = logging.getLogger(__name__)

FALLBACK_RESPONSE = "Извините, сервис временно недоступен. Пожалуйста, попробуйте позже."


class EmbeddingCache:
    """LRU cache for text embeddings — identical messages skip API call."""
    def __init__(self, maxsize: int = 100):
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._maxsize = maxsize

    def _key(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    def get(self, text: str) -> list[float] | None:
        key = self._key(text)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def set(self, text: str, embedding: list[float]):
        key = self._key(text)
        self._cache[key] = embedding
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)


_embedding_cache = EmbeddingCache()

_HTTX_HAS_NEW_PROXY_API = tuple(int(x) for x in httpx.__version__.split(".")[:2]) >= (0, 28)

RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ProxyError,
    httpx.RemoteProtocolError,
)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class GeminiProvider(BaseAIProvider):
    def __init__(self, api_key: str, model: str, embedding_model: str, proxy_url: str | None = None):
        self.api_key = api_key
        self.model = model
        self.embedding_model = embedding_model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self._client_kwargs: dict[str, object] = {"timeout": 60.0}

        if proxy_url:
            safe_url = proxy_url
            if "@" in proxy_url:
                safe_url = "http://***:***@" + proxy_url.split("@", 1)[1]
            logger.info("Using proxy: %s (httpx %s, new_api=%s)", safe_url, httpx.__version__, _HTTX_HAS_NEW_PROXY_API)

            if _HTTX_HAS_NEW_PROXY_API:
                self._client_kwargs["proxy"] = proxy_url
            else:
                self._client_kwargs["proxies"] = {
                    "http://": proxy_url,
                    "https://": proxy_url,
                }
        else:
            logger.info("No proxy configured, connecting directly to Gemini API")

    def _is_retryable_error(self, exc: Exception) -> bool:
        if isinstance(exc, RETRYABLE_EXCEPTIONS):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in RETRYABLE_STATUS_CODES
        return False

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS) | retry_if_exception_type(httpx.HTTPStatusError),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _make_request(self, url: str, payload: dict) -> httpx.Response:
        async with httpx.AsyncClient(**self._client_kwargs) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response

    async def get_embedding(self, text: str) -> list[float]:
        # Cache hit — не дёргаем API
        cached = _embedding_cache.get(text)
        if cached is not None:
            return cached

        url = f"{self.base_url}/models/{self.embedding_model}:embedContent?key={self.api_key}"
        payload = {
            "model": f"models/{self.embedding_model}",
            "content": {"parts": [{"text": text}]},
        }
        try:
            logger.debug("Sending embedding request to %s", url[:80] + "...")
            response = await self._make_request(url, payload)
            data = response.json()
            embedding = data["embedding"]["values"]
            _embedding_cache.set(text, embedding)
            return embedding
        except httpx.HTTPStatusError as e:
            logger.error(
                "Gemini embedding API HTTP error: status=%s, body=%s",
                e.response.status_code,
                e.response.text[:500],
            )
        except httpx.ProxyError as e:
            logger.error("Gemini embedding proxy error: %s\n%s", e, traceback.format_exc())
        except httpx.ConnectError as e:
            logger.error("Gemini embedding connection error (check proxy/host): %s\n%s", e, traceback.format_exc())
        except httpx.TimeoutException as e:
            logger.error("Gemini embedding timeout (60s exceeded): %s\n%s", e, traceback.format_exc())
        except httpx.RequestError as e:
            logger.error("Gemini embedding request failed: %s\n%s", e, traceback.format_exc())
        except Exception as e:
            logger.error("Unexpected error in get_embedding: %s\n%s", e, traceback.format_exc())
        return []

    async def generate_response(
        self,
        system_instruction: str,
        history: list,
        current_message: str,
    ) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"

        contents = []
        for msg in history:
            role = "model" if msg.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})
        contents.append({"role": "user", "parts": [{"text": current_message}]})

        payload = {
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "contents": contents,
        }
        try:
            logger.debug(
                "Sending generation request to model=%s proxy=%s",
                self.model,
                bool(self._client_kwargs.get("proxy") or self._client_kwargs.get("proxies")),
            )
            response = await self._make_request(url, payload)
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except httpx.HTTPStatusError as e:
            logger.error(
                "Gemini generation API HTTP error: status=%s, body=%s",
                e.response.status_code,
                e.response.text[:500],
            )
        except httpx.ProxyError as e:
            logger.error("Gemini generation proxy error: %s\n%s", e, traceback.format_exc())
        except httpx.ConnectError as e:
            logger.error("Gemini generation connection error (check proxy/host): %s\n%s", e, traceback.format_exc())
        except httpx.TimeoutException as e:
            logger.error("Gemini generation timeout (60s exceeded): %s\n%s", e, traceback.format_exc())
        except httpx.RequestError as e:
            logger.error("Gemini generation request failed: %s\n%s", e, traceback.format_exc())
        except (KeyError, IndexError) as e:
            logger.error("Gemini generation API unexpected response format: %s\n%s", e, traceback.format_exc())
        except Exception as e:
            logger.error("Unexpected error in generate_response: %s\n%s", e, traceback.format_exc())
        return FALLBACK_RESPONSE

    async def generate_response_streaming(
        self,
        system_instruction: str,
        history: list,
        current_message: str,
    ) -> AsyncGenerator[tuple[str, str], None]:
        """
        Stream response from Gemini.
        Yields (token, accumulated_text) tuples.
        """
        url = f"{self.base_url}/models/{self.model}:streamGenerateContent?alt=sse&key={self.api_key}"

        contents = []
        for msg in history:
            role = "model" if msg.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})
        contents.append({"role": "user", "parts": [{"text": current_message}]})

        payload = {
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "contents": contents,
        }

        accumulated = ""
        try:
            async with httpx.AsyncClient(**self._client_kwargs) as client:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                candidates = data.get("candidates", [])
                                if candidates:
                                    parts = candidates[0].get("content", {}).get("parts", [])
                                    if parts:
                                        token = parts[0].get("text", "")
                                        accumulated += token
                                        yield (token, accumulated)
                            except json.JSONDecodeError:
                                continue
        except httpx.HTTPStatusError as e:
            logger.error("Gemini stream HTTP error: status=%s, body=%s", e.response.status_code, e.response.text[:500])
        except httpx.ProxyError as e:
            logger.error("Gemini stream proxy error: %s", e)
        except httpx.ConnectError as e:
            logger.error("Gemini stream connection error: %s", e)
        except httpx.TimeoutException as e:
            logger.error("Gemini stream timeout: %s", e)
        except Exception as e:
            logger.error("Gemini stream error: %s", e)

        yield ("", accumulated)
