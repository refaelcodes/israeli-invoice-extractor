# -*- coding: utf-8 -*-
"""Абстракция AI-провайдера — сердце переключателя режимов.

Единый интерфейс `AIProvider.extract(image_b64) -> dict`, за которым скрыт транспорт:
    ApiProvider   ai_mode="api"   прямой Anthropic Messages API (биллинг, для клиента)
    SdkProvider   ai_mode="sdk"   Claude Agent SDK (claude_agent_sdk) через подписку (для разработки)
    MockProvider  ai_mode="mock"  офлайн-заглушка без сети (для UI/проверки сборки запроса)

Контракт извлечения (EXTRACTION_TOOL / SYSTEM) одинаков для всех режимов — это гарантирует,
что JSON на выходе имеет одну и ту же форму независимо от того, чем он получен. Схема совпадает
с ground-truth генератора; отсутствующие поля модель оставляет null.
"""
import os
import json
import asyncio

# --- Схема извлечения (совпадает с ground-truth генератора; лишние поля -> null) -----------
EXTRACTION_TOOL = {
    "name": "record_document",
    "description": "Записать все данные, извлечённые из финансового документа. "
                   "Заполняй только реально видимые поля; отсутствующие оставляй null. "
                   "Числа — как числа без валютных символов и разделителей тысяч.",
    "input_schema": {
        "type": "object",
        "properties": {
            "doc_type": {"type": "string",
                "description": "Тип документа как на бланке (иврит): напр. חשבונית מס, קבלה, תלוש שכר, דף חשבון בנק, שיק"},
            "doc_number": {"type": ["string", "number", "null"]},
            "issue_date": {"type": ["string", "null"],
                "description": "DD/MM/YYYY. Дата выписки документа (חשבונית/קבלה и т.п.). "
                               "Для ЛЮБОГО документа кроме чека и банковской выписки дату клади СЮДА, "
                               "а не в поле date."},
            "seller": {"type": ["object", "null"], "properties": {
                "name": {"type": ["string", "null"]}, "vat_id": {"type": ["string", "null"]}}},
            "customer": {"type": ["object", "null"], "properties": {
                "name": {"type": ["string", "null"]}, "id": {"type": ["string", "null"]}}},
            "currency": {"type": ["string", "null"]},
            "line_items": {"type": ["array", "null"], "items": {"type": "object", "properties": {
                "description": {"type": ["string", "null"]},
                "unit": {"type": ["string", "null"]},
                "quantity": {"type": ["number", "null"]},
                "unit_price": {"type": ["number", "null"]},
                "line_total": {"type": ["number", "null"]}}}},
            "subtotal": {"type": ["number", "null"]},
            "vat_rate": {"type": ["number", "null"], "description": "доля, напр. 0.18"},
            "vat_amount": {"type": ["number", "null"]},
            "total": {"type": ["number", "null"]},
            "allocation_number": {"type": ["string", "null"], "description": "מספר הקצאה, если есть"},
            "is_paid": {"type": ["boolean", "null"]},
            # payslip
            "period": {"type": ["string", "null"], "description": "MM/YYYY"},
            "employer": {"type": ["object", "null"], "properties": {
                "name": {"type": ["string", "null"]}, "vat_id": {"type": ["string", "null"]}}},
            "employee": {"type": ["object", "null"], "properties": {
                "name": {"type": ["string", "null"]}, "id": {"type": ["string", "null"]}}},
            "earnings": {"type": ["array", "null"], "items": {"type": "object", "properties": {
                "name": {"type": ["string", "null"]}, "amount": {"type": ["number", "null"]}}}},
            "gross": {"type": ["number", "null"]},
            "deductions": {"type": ["array", "null"], "items": {"type": "object", "properties": {
                "name": {"type": ["string", "null"]}, "amount": {"type": ["number", "null"]}}}},
            "total_deductions": {"type": ["number", "null"]},
            "net_pay": {"type": ["number", "null"]},
            # bank / cheque
            "bank": {"type": ["string", "null"]},
            "bank_code": {"type": ["string", "number", "null"]},
            "branch": {"type": ["string", "number", "null"]},
            "account_number": {"type": ["string", "number", "null"]},
            "account_holder": {"type": ["string", "null"]},
            "statement_date": {"type": ["string", "null"], "description": "DD/MM/YYYY"},
            "transactions": {"type": ["array", "null"], "items": {"type": "object", "properties": {
                "date": {"type": ["string", "null"], "description": "DD/MM/YYYY"},
                "description": {"type": ["string", "null"]},
                "debit": {"type": ["number", "null"]},
                "credit": {"type": ["number", "null"]},
                "balance": {"type": ["number", "null"]}}}},
            "closing_balance": {"type": ["number", "null"]},
            # cheque
            "cheque_number": {"type": ["string", "number", "null"]},
            "date": {"type": ["string", "null"],
                "description": "DD/MM/YYYY. ТОЛЬКО для чека (שיק) — дата на чеке. "
                               "Для счетов/квитанций используй issue_date, для выписки — statement_date."},
            "amount": {"type": ["number", "null"]},
            "amount_words": {"type": ["string", "null"], "description": "сумма прописью (иврит)"},
            "micr": {"type": ["string", "null"], "description": "MICR-строка внизу чека"},
            "payee": {"type": ["string", "null"]},
            "payer": {"type": ["string", "null"]},
        },
        "required": ["doc_type"],
    },
}

SYSTEM = ("Ты — точный экстрактор данных из израильских финансовых документов. "
          "Извлекай ровно то, что видно на изображении. Не додумывай значения. "
          "Иврит сохраняй как есть. Числа возвращай без ₪ и разделителей тысяч "
          "(27,081.00 -> 27081.0). Валюту возвращай ISO-кодом: символ ₪ или ש\"ח -> \"ILS\". "
          "Если изображений несколько — это СТРАНИЦЫ ОДНОГО документа по порядку: объедини их "
          "в одну запись (line_items/transactions собери со всех страниц, итоги бери с последней). "
          "Вызови инструмент record_document ровно один раз.")

USER_TEXT = "Извлеки все данные из этого документа и вызови record_document."


def _image_block(image_b64: str, media_type: str = "image/png") -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}}


def _normalize_images(images, media_type="image/png"):
    """Принять str (одна картинка), dict или список dict -> список {b64, media_type}."""
    if isinstance(images, str):
        return [{"b64": images, "media_type": media_type}]
    if isinstance(images, dict):
        return [images]
    return list(images)


def _content_blocks(images) -> list:
    """Картинки ПЕРЕД текстом. Несколько страниц -> несколько image-блоков подряд."""
    pages = _normalize_images(images)
    blocks = [_image_block(p["b64"], p.get("media_type", "image/png")) for p in pages]
    if len(pages) > 1:
        blocks.append({"type": "text", "text": f"Документ состоит из {len(pages)} страниц (по порядку выше)."})
    blocks.append({"type": "text", "text": USER_TEXT})
    return blocks


def build_request(images, model: str, max_tokens: int, media_type: str = "image/png") -> dict:
    """Тело запроса Messages API (без сети). Используется ApiProvider и MockProvider.
    `images` — base64-строка ИЛИ список {b64, media_type} (страницы одного документа)."""
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": SYSTEM,
        "tools": [EXTRACTION_TOOL],
        "tool_choice": {"type": "tool", "name": "record_document"},  # форсируем структурный вывод
        "messages": [{"role": "user", "content": _content_blocks(
            _normalize_images(images, media_type))}],
    }


def parse_tool_response(response) -> dict:
    """Достать input из tool_use-блока. Работает и на реальном ответе SDK, и на dict-стабе."""
    blocks = response["content"] if isinstance(response, dict) else response.content
    for b in blocks:
        btype = b["type"] if isinstance(b, dict) else b.type
        if btype == "tool_use":
            return b["input"] if isinstance(b, dict) else b.input
    raise RuntimeError("В ответе нет tool_use блока")


# ============================================================================ провайдеры
class AIProvider:
    """Базовый интерфейс. Реализации переопределяют extract().

    `images` — base64-строка (одна страница) ИЛИ список {b64, media_type} (страницы одного
    документа по порядку). Многостраничные PDF отдаются моделью как один документ.
    """
    mode = "base"

    def __init__(self, model: str, max_tokens: int = 2048, api_key: str = None):
        self.model = model
        self.max_tokens = max_tokens
        self.api_key = api_key      # ключ из UI (в памяти сессии), приоритетнее ANTHROPIC_API_KEY

    def extract(self, images, media_type: str = "image/png") -> dict:
        raise NotImplementedError

    def info(self) -> dict:
        return {"mode": self.mode, "model": self.model, "max_tokens": self.max_tokens}


class ApiProvider(AIProvider):
    """Прямой Anthropic Messages API (нужен ANTHROPIC_API_KEY + сеть; биллинг)."""
    mode = "api"

    def extract(self, images, media_type: str = "image/png") -> dict:
        import anthropic
        # ключ из UI (в памяти сессии, в файлы не пишется) ИЛИ из ANTHROPIC_API_KEY (.env)
        client = anthropic.Anthropic(api_key=self.api_key) if self.api_key else anthropic.Anthropic()
        req = build_request(images, self.model, self.max_tokens, media_type)
        resp = client.messages.create(**req)
        return parse_tool_response(resp)


class MockProvider(AIProvider):
    """Офлайн: возвращает форму запроса без вызова сети (бывший --dry-run)."""
    mode = "mock"

    def extract(self, images, media_type: str = "image/png") -> dict:
        req = build_request(images, self.model, self.max_tokens, media_type)
        pages = len(_normalize_images(images, media_type))
        return {
            "doc_type": "[MOCK]",
            "_note": "MOCK-режим: сеть не вызывалась, это форма запроса, не извлечённые данные.",
            "_pages": pages,
            "_request_shape": {k: (v if k != "messages" else f"[{pages}×image+text]") for k, v in req.items()},
        }


class SdkProvider(AIProvider):
    """Claude Agent SDK (claude_agent_sdk) через подписку/локальную авторизацию Claude Code.

    Структурный вывод достигается in-process MCP-инструментом record_document с той же схемой:
    хендлер захватывает переданные моделью аргументы (это и есть извлечённый JSON).
    Проверено spike'ом: inline base64 PNG проходит, tool вызывается, поля извлекаются корректно.
    """
    mode = "sdk"

    def extract(self, images, media_type: str = "image/png") -> dict:
        return asyncio.run(self._aextract(images, media_type))

    async def _aextract(self, images, media_type: str = "image/png") -> dict:
        import claude_agent_sdk as sdk

        captured = {}

        @sdk.tool("record_document", EXTRACTION_TOOL["description"], EXTRACTION_TOOL["input_schema"])
        async def record_document(args):
            captured["data"] = args
            return {"content": [{"type": "text", "text": "saved"}]}

        server = sdk.create_sdk_mcp_server("rec", tools=[record_document])
        opts = sdk.ClaudeAgentOptions(
            system_prompt=SYSTEM,
            model=self.model,
            mcp_servers={"rec": server},
            allowed_tools=["mcp__rec__record_document"],
            permission_mode="bypassPermissions",
            setting_sources=[],   # не подтягивать CLAUDE.md/настройки проекта в вложенный агент
            max_turns=3,
        )

        content = _content_blocks(_normalize_images(images, media_type))

        async def prompts():
            yield {"type": "user", "message": {"role": "user", "content": content}}

        async for _msg in sdk.query(prompt=prompts(), options=opts):
            pass  # аргументы модели захватываются в record_document

        if "data" not in captured:
            raise RuntimeError("SDK не вызвал record_document — структурный вывод не получен")
        return captured["data"]


_PROVIDERS = {"api": ApiProvider, "sdk": SdkProvider, "mock": MockProvider}


def get_provider(cfg, api_key: str = None) -> AIProvider:
    """Фабрика: выбрать провайдера по cfg.ai_mode. cfg — _core.config.Config или dict.
    api_key (опц.) — ключ из UI; приоритетнее ANTHROPIC_API_KEY, в файлы не пишется."""
    mode = cfg.ai_mode if hasattr(cfg, "ai_mode") else cfg.get("ai_mode", "mock")
    model = cfg.model if hasattr(cfg, "model") else cfg.get("model", "claude-opus-4-8")
    max_tokens = (cfg.extractor if hasattr(cfg, "extractor") else cfg.get("extractor", {})).get("max_tokens", 2048)
    cls = _PROVIDERS.get(mode)
    if cls is None:
        raise ValueError(f"Неизвестный ai_mode='{mode}'. Ожидается один из {list(_PROVIDERS)}")
    return cls(model=model, max_tokens=max_tokens, api_key=api_key)
