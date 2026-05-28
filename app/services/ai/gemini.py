import logging
import traceback
from typing import List

import httpx

from app.services.ai.base import BaseAIProvider

logger = logging.getLogger(__name__)

FALLBACK_RESPONSE = "Извините, сервис временно недоступен. Пожалуйста, попробуйте позже."

# httpx >= 0.28 uses `proxy` (singular); older versions use `proxies` (plural)
_HTTX_HAS_NEW_PROXY_API = tuple(int(x) for x in httpx.__version__.split(".")[:2]) >= (0, 28)


class GeminiProvider(BaseAIProvider):

    def __init__(self, api_key: str, model: str, embedding_model: str, proxy_url: str | None = None):
        self.api_key = api_key
        self.model = model
        self.embedding_model = embedding_model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self._client_kwargs = {"timeout": 60.0}

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

    async def get_embedding(self, text: str) -> List[float]:
        url = f"{self.base_url}/models/{self.embedding_model}:embedContent?key={self.api_key}"
        payload = {
            "model": f"models/{self.embedding_model}",
            "content": {"parts": [{"text": text}]},
        }
        try:
            async with httpx.AsyncClient(**self._client_kwargs) as client:
                logger.debug("Sending embedding request to %s", url[:80] + "...")
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["embedding"]["values"]
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
            async with httpx.AsyncClient(**self._client_kwargs) as client:
                logger.debug("Sending generation request to model=%s proxy=%s", self.model, bool(self._client_kwargs.get("proxy") or self._client_kwargs.get("proxies")))
                response = await client.post(url, json=payload)
                response.raise_for_status()
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
