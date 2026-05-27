import logging
import re

logger = logging.getLogger(__name__)

NAME_PATTERNS = [
    r"\bМеня\s+зовут\s+([A-ZА-Я][a-zа-яё]+\s+[A-ZА-Я][a-zа-яё]+)",
    r"\bЯ\s+—?\s*([A-ZА-Я][a-zа-яё]+\s+[A-ZА-Я][a-zа-яё]+)",
    r"\bМоё\s+имя\s+([A-ZА-Я][a-zа-яё]+\s+[A-ZА-Я][a-zа-яё]+)",
    r"\b[Зз]овут\s+([A-ZА-Я][a-zа-яё]+\s+[A-ZА-Я][a-zа-яё]+)",
]

PHONE_PATTERN = re.compile(
    r"(?:\+7|8|7)?[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
)

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

URL_PATTERN = re.compile(r"https?://[^\s]+|t\.me/[a-zA-Z0-9_]+|@[a-zA-Z0-9_]+")

LINKEDIN_PATTERN = re.compile(r"(?:linkedin\.com/in/|linkedin\.com/company/)[a-zA-Z0-9_-]+")


async def anonymize_text(text: str) -> str:
    if not text:
        return text

    result = text

    result = LINKEDIN_PATTERN.sub("[LINK]", result)
    result = URL_PATTERN.sub("[LINK]", result)
    result = EMAIL_PATTERN.sub("[EMAIL]", result)
    result = PHONE_PATTERN.sub("[PHONE]", result)

    for pattern in NAME_PATTERNS:
        result = re.sub(pattern, r"Меня зовут [NAME]", result)

    matches = re.findall(r"\b([A-ZА-Я][a-zа-яё]+)\b", result)
    known_non_names = {"Привет", "Пока", "Да", "Нет", "Хорошо", "Спасибо", "Здравствуйте", "Добрый", "Пожалуйста"}
    for match in matches:
        if match not in known_non_names:
            context_before = re.findall(rf"(?:^|[\s.,!?])(я|моё|мое)\s+{re.escape(match)}\b", result[:result.find(match)], re.IGNORECASE)
            if context_before:
                result = result.replace(match, "[NAME]", 1)

    logger.debug("Anonymized text successfully")
    return result
