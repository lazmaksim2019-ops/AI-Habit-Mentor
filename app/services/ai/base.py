from abc import ABC, abstractmethod
from typing import List


class BaseAIProvider(ABC):

    @abstractmethod
    async def get_embedding(self, text: str) -> List[float]:
        ...

    @abstractmethod
    async def generate_response(
        self,
        system_instruction: str,
        history: list,
        current_message: str,
    ) -> str:
        ...
