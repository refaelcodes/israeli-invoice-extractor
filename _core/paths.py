# -*- coding: utf-8 -*-
"""Кроссплатформенное разрешение путей.

Заменяет захардкоженный Linux-путь `OUT = "/mnt/user-data/outputs/israeli_docs"`
из старого generate.py. Корень проекта — папка israeli_docs/ (родитель пакета _core).
Все относительные пути в config.json трактуются относительно этого корня.
"""
import os
from pathlib import Path

# .../israeli_docs/_core/paths.py -> корень проекта = .../israeli_docs
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Каталоги генератора со шаблонами (нужны для sys.path при импорте fake/templates)
GENERATOR_DIR = PROJECT_ROOT / "_generator"
EXTRACTOR_DIR = PROJECT_ROOT / "_extractor"


def resolve(path_like, base: Path = PROJECT_ROOT) -> Path:
    """Абсолютный путь: если относительный — от корня проекта; абсолютный — как есть."""
    p = Path(os.path.expanduser(str(path_like)))
    return p if p.is_absolute() else (base / p)


def ensure_dir(path_like) -> Path:
    """Создать каталог (и родителей) и вернуть абсолютный Path."""
    p = resolve(path_like)
    p.mkdir(parents=True, exist_ok=True)
    return p
