# -*- coding: utf-8 -*-
"""Единая точка правды для обеих программ.

Читает config.json (из корня проекта) и .env (через python-dotenv). Если config.json
отсутствует — создаётся из DEFAULTS. Ключевой параметр — `ai_mode`:
    "api"  — прямой Anthropic Messages API (биллинг, для реального клиента)
    "sdk"  — Claude Agent SDK (claude_agent_sdk) через подписку (для разработки/тестов)
    "mock" — офлайн-заглушка без сети (бывший --dry-run; для UI и проверки сборки)
"""
import json
import copy
from pathlib import Path

from dotenv import load_dotenv

from . import paths

CONFIG_PATH = paths.PROJECT_ROOT / "config.json"

# Валидные model id (сверено, июль 2026). claude-opus-4-8 — текущий дефолт экстрактора.
VALID_MODELS = [
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-haiku-4-5-20251001",
    "claude-fable-5",
]
VALID_MODES = ("api", "sdk", "mock")

# Ключи в REGISTRY генератора (ASCII-имена папок). Дублируется как дефолт, чтобы
# config.py не тянул тяжёлые импорты (playwright) при простом чтении конфига.
ALL_DOC_TYPES = [
    "01_invoice_tax", "02_invoice_tax_receipt", "03_invoice_proforma",
    "04_receipt", "05_invoice_credit", "06_payslip",
    "07_bank_statement", "08_cheque",
]

DEFAULTS = {
    "ai_mode": "mock",
    "model": "claude-opus-4-8",
    "generator": {
        "output_dir": "output",
        "seed": 20260707,
        "variants": 3,
        "doc_types": list(ALL_DOC_TYPES),
        "png_dpi": 150,
    },
    "extractor": {
        # "." — коммитнутый датасет из 24 документов в корне (01_../08_..); работает из коробки.
        # Чтобы оценивать свежесгенерированные документы — укажи "output" (совпадает с generator.output_dir).
        "dataset_dir": ".",
        "pred_dir": "pred",
        "max_tokens": 4096,   # 2048 обрезало tool-вызов на документах с многими позициями
        "max_pages": 10,      # сколько страниц PDF отдавать модели (страницы одного документа)
        "pdf_dpi": 150,       # разрешение растеризации PDF -> PNG
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Рекурсивное слияние: значения override перекрывают base, вложенные dict сливаются."""
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    """Обёртка над словарём настроек с типизированным доступом и валидацией."""

    def __init__(self, data: dict):
        self._data = data

    # --- верхний уровень ---
    @property
    def ai_mode(self) -> str:
        return self._data["ai_mode"]

    @property
    def model(self) -> str:
        return self._data["model"]

    @property
    def generator(self) -> dict:
        return self._data["generator"]

    @property
    def extractor(self) -> dict:
        return self._data["extractor"]

    def as_dict(self) -> dict:
        return copy.deepcopy(self._data)

    # --- разрешённые абсолютные пути ---
    def output_dir(self) -> Path:
        return paths.resolve(self.generator["output_dir"])

    def dataset_dir(self) -> Path:
        return paths.resolve(self.extractor["dataset_dir"])

    def pred_dir(self) -> Path:
        return paths.resolve(self.extractor["pred_dir"])

    def validate(self) -> list:
        """Вернуть список предупреждений (не бросает — GUI покажет их пользователю)."""
        warns = []
        if self.ai_mode not in VALID_MODES:
            warns.append(f"ai_mode='{self.ai_mode}' неизвестен; ожидается {VALID_MODES}")
        if self.model not in VALID_MODELS:
            warns.append(f"model='{self.model}' нет в списке проверенных {VALID_MODELS}")
        bad = [t for t in self.generator.get("doc_types", []) if t not in ALL_DOC_TYPES]
        if bad:
            warns.append(f"неизвестные doc_types: {bad}")
        return warns


def load(path: Path = CONFIG_PATH) -> Config:
    """Загрузить .env + config.json (создав дефолтный при отсутствии)."""
    load_dotenv(paths.PROJECT_ROOT / ".env")
    if path.exists():
        user = json.loads(path.read_text(encoding="utf-8"))
    else:
        user = {}
        path.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    return Config(_deep_merge(DEFAULTS, user))


def save(cfg: Config, path: Path = CONFIG_PATH) -> None:
    """Сохранить конфиг обратно в config.json (для тумблера режима в UI)."""
    path.write_text(json.dumps(cfg.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
