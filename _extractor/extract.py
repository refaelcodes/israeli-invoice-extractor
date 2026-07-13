# -*- coding: utf-8 -*-
"""Экстрактор данных из израильских финансовых документов (PDF/PNG/JPG) -> структурный JSON.

Подход: vision-LLM (Claude) + tool-use со СХЕМОЙ. Транспорт выбирается через _core.ai_provider
по config.ai_mode ("api" | "sdk" | "mock") — схема EXTRACTION_TOOL/SYSTEM одна на все режимы.

    python extract.py путь/к/документу.png            > out.json   # режим берётся из config.json
    python extract.py путь/к/документу.pdf  --mode api > out.json
    python extract.py doc.png --dry-run                            # == --mode mock (без сети)

PDF растеризуется через PyMuPDF (fitz) — системный poppler не нужен.
"""
import os
import sys
import json
import base64

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from _core import config, ai_provider  # noqa: E402

# Re-export контракта извлечения (для обратной совместимости и тестов)
EXTRACTION_TOOL = ai_provider.EXTRACTION_TOOL
SYSTEM = ai_provider.SYSTEM


def load_pages_b64(path, max_pages=10, pdf_dpi=150):
    """Файл -> список страниц [{b64, media_type}].

    PNG/JPG -> одна страница. PDF -> ВСЕ страницы (до max_pages) через PyMuPDF.
    Раньше бралась только первая страница — многостраничные счета молча теряли данные.
    """
    ext = path.lower().rsplit(".", 1)[-1]
    if ext == "png":
        return [{"b64": base64.standard_b64encode(open(path, "rb").read()).decode(),
                 "media_type": "image/png"}]
    if ext in ("jpg", "jpeg"):
        return [{"b64": base64.standard_b64encode(open(path, "rb").read()).decode(),
                 "media_type": "image/jpeg"}]
    if ext == "pdf":
        import fitz  # PyMuPDF
        doc = fitz.open(path)
        try:
            n = min(doc.page_count, max_pages)
            pages = []
            for i in range(n):
                png_bytes = doc.load_page(i).get_pixmap(dpi=pdf_dpi).tobytes("png")
                pages.append({"b64": base64.standard_b64encode(png_bytes).decode(),
                              "media_type": "image/png"})
            if doc.page_count > max_pages:
                print(f"[warn] PDF имеет {doc.page_count} страниц, взято первых {max_pages} "
                      f"(увеличь extractor.max_pages)", file=sys.stderr)
            return pages
        finally:
            doc.close()
    raise ValueError(f"Неподдерживаемый формат: {ext}")


def load_image_b64(path):
    """Совместимость: (base64, media_type) первой страницы."""
    p = load_pages_b64(path, max_pages=1)[0]
    return p["b64"], p["media_type"]


def extract(path, cfg=None, mode=None):
    """Извлечь данные из документа. mode переопределяет config.ai_mode при необходимости."""
    cfg = cfg or config.load()
    if mode:
        cfg._data["ai_mode"] = mode
    e = cfg.extractor
    provider = ai_provider.get_provider(cfg)
    pages = load_pages_b64(path, max_pages=e.get("max_pages", 10), pdf_dpi=e.get("pdf_dpi", 150))
    return provider.extract(pages)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    args = sys.argv[1:]
    m = None
    if "--dry-run" in args:
        m = "mock"
    if "--mode" in args:
        m = args[args.index("--mode") + 1]
    path = [a for a in args if not a.startswith("--") and a != m][0]
    out = extract(path, mode=m)
    print(json.dumps(out, ensure_ascii=False, indent=2))
