import logging
import re

logger = logging.getLogger(__name__)

NAME_PATTERNS = [
    r"\bМеня\s+зовут\s+([A-ZА-Я][a-zа-яё]+\s+[A-ZА-Я][a-zа-яё]+)",
    r"\bЯ\s+—?\s*([A-ZА-Я][a-zа-яё]+\s+[A-ZА-Я][a-zа-яё]+)",
    r"\bМоё\s+имя\s+([A-ZА-Я][a-zа-яё]+\s+[A-ZА-Я][a-zа-яё]+)",
    r"\b[Зз]овут\s+([A-ZА-Я][a-zа-яё]+\s+[A-ZА-Я][a-zа-яё]+)",
]

PHONE_PATTERN = re.compile(r"(?:\+7|8|7)?[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b")

EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")

URL_PATTERN = re.compile(r"https?://[^\s]+|t\.me/[a-zA-Z0-9_]+|@[a-zA-Z0-9_]+")

LINKEDIN_PATTERN = re.compile(r"(?:linkedin\.com/in/|linkedin\.com/company/)[a-zA-Z0-9_-]+")

PASSPORT_PATTERN = re.compile(r"\b\d{4}\s?\d{6}\b")

INN_PATTERN = re.compile(r"(?<!\d)\b\d{10}\b(?!\d)|\b\d{12}\b")

SNILS_PATTERN = re.compile(r"\b\d{3}[\-\s]?\d{3}[\-\s]?\d{3}[\-\s]?\d{2}\b")

BANK_CARD_PATTERN = re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b")

ADDRESS_PATTERNS = [
    r"\b(?:ул\.|улица|пр\.|проспект|пер\.|переулок|ш\.|шоссе|д\.|дом|к\.|корпус|оф\.|офис)\.?\s*[А-Яа-яA-Za-z0-9\s\-]+\d+[абвг]?(?:\s*,\s*\d+)?",
    r"\bг\.?\s*[А-Яа-я\-]+\b",
    r"\b(?:обл\.|область|край|респ\.|республика)\.?\s*[А-Яа-я\-]+\b",
]

IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

KNOWN_NON_NAMES = {
    "Привет",
    "Пока",
    "Да",
    "Нет",
    "Хорошо",
    "Спасибо",
    "Здравствуйте",
    "Добрый",
    "Пожалуйста",
    "Извините",
    "Согласен",
    "Не согласен",
    "Плохо",
    "Нормально",
    "Отлично",
    "Ужасно",
    "Москва",
    "Санкт-Петербург",
    "Казань",
    "Новосибирск",
    "Екатеринбург",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
}


async def anonymize_text(text: str) -> str:
    if not text:
        return text

    result = text

    # Порядок важен: сначала более специфичные паттерны, потом общие
    # EMAIL перед URL — чтобы email@example.com не матчился как ссылка
    result = EMAIL_PATTERN.sub("[EMAIL]", result)
    # INN перед PHONE — чтобы 10-значные ИНН не матчились как телефон
    result = INN_PATTERN.sub("[INN]", result)
    result = PASSPORT_PATTERN.sub("[PASSPORT]", result)
    result = SNILS_PATTERN.sub("[SNILS]", result)
    result = BANK_CARD_PATTERN.sub("[CARD]", result)
    result = PHONE_PATTERN.sub("[PHONE]", result)
    result = LINKEDIN_PATTERN.sub("[LINK]", result)
    result = URL_PATTERN.sub("[LINK]", result)
    result = IP_PATTERN.sub("[IP]", result)

    for pattern in ADDRESS_PATTERNS:
        result = re.sub(pattern, "[ADDRESS]", result, flags=re.IGNORECASE)

    for pattern in NAME_PATTERNS:
        result = re.sub(pattern, r"Меня зовут [NAME]", result)

    matches = re.findall(r"\b([A-ZА-Я][a-zа-яё]+)\b", result)
    for match in matches:
        if match not in KNOWN_NON_NAMES:
            context_before = re.findall(
                rf"(?:^|[\s.,!?])(я|моё|мое|зовут|имя)\s+{re.escape(match)}\b",
                result[: result.find(match)],
                re.IGNORECASE,
            )
            if context_before:
                result = result.replace(match, "[NAME]", 1)

    logger.debug("Anonymized text successfully")
    return result
