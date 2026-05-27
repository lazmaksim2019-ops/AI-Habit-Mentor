import logging
from typing import List

import httpx

from app.services.ai.base import BaseAIProvider

logger = logging.getLogger(__name__)

FALLBACK_RESPONSE = "Извините, сервис временно недоступен. Пожалуйста, попробуйте позже."


class GeminiProvider(BaseAIProvider):

    def __init__(self, api_key: str, model: str, embedding_model: str, proxy_url: str | None = None):
        self.api_key = api_key
        self.model = model
        self.embedding_model = embedding_model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self._client_kwargs = {"timeout": 30.0}
        if proxy_url:
            self._client_kwargs["proxies"] = {
                "http://": proxy_url,
                "https://": proxy_url,
            }

    async def get_embedding(self, text: str) -> List[float]:
        url = f"{self.base_url}/models/{self.embedding_model}:embedContent?key={self.api_key}"
        payload = {
            "model": f"models/{self.embedding_model}",
            "content": {"parts": [{"text": text}]},
        }
        try:
            async with httpx.AsyncClient(**self._client_kwargs) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["embedding"]["values"]
        except httpx.HTTPStatusError as e:
            logger.error("Gemini embedding API HTTP error: %s | status=%s", e, e.response.status_code)
        except httpx.RequestError as e:
            logger.error("Gemini embedding API request failed: %s", e)
        except Exception as e:
            logger.error("Unexpected error in get_embedding: %s", e)
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
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
        except httpx.HTTPStatusError as e:
            logger.error("Gemini generation API HTTP error: %s | status=%s", e, e.response.status_code)
        except httpx.RequestError as e:
            logger.error("Gemini generation API request failed: %s", e)
        except (KeyError, IndexError) as e:
            logger.error("Gemini generation API unexpected response format: %s", e)
        except Exception as e:
            logger.error("Unexpected error in generate_response: %s", e)
        return FALLBACK_RESPONSE
