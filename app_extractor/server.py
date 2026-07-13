# -*- coding: utf-8 -*-
"""ПРОГРАММА 2 — Экстрактор данных + сверка с ground-truth (веб-GUI, FastAPI).

  * переключатель режима AI (api / sdk / mock) прямо в UI, пишется в config.json;
  * извлечение одного документа (загрузка файла ИЛИ выбор из датасета);
  * экран сверки: поле-за-полем predicted vs ground-truth, точность %, слабейшие поля;
  * батч по всему датасету со стримингом прогресса (SSE).

Запуск:  python app_extractor/server.py   (откроет http://127.0.0.1:8002)
"""
import os
import sys
import json
import queue
import asyncio
import tempfile
import threading
import webbrowser

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for p in (_ROOT, os.path.join(_ROOT, "_extractor")):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import extract          # _extractor/extract.py
import batch            # _extractor/batch.py
from _core import config, ai_provider, validate  # noqa: E402

app = FastAPI(title="Israeli Docs — Экстрактор")
STATIC = os.path.join(_HERE, "static")

# API-ключ, введённый в UI. Живёт ТОЛЬКО в памяти процесса — не пишется в config.json/файлы/репо.
# Приоритетнее ANTHROPIC_API_KEY (.env). Сбрасывается при перезапуске сервера.
_RUNTIME_KEY = {"api_key": None}

# Флаг онбординга ТЕКУЩЕГО запуска сервера. Сбрасывается при рестарте -> модалка выбора
# доступа (API / SDK / офлайн-демо) показывается при каждом запуске, пока пользователь не выберет.
_SESSION = {"onboarded": False}


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _truth_index():
    """id -> {fields, png, doc_type} по ground-truth файлам датасета.

    Эталоном считаем ТОЛЬКО записи с обоими ключами (fields + files). Файлы предсказаний
    ({id, fields}) не имеют files — а pred_dir может лежать внутри dataset_dir (напр. "."),
    поэтому его дополнительно исключаем явно.
    """
    cfg = config.load()
    base = cfg.dataset_dir()
    pred_abs = cfg.pred_dir().resolve()
    idx = {}
    if base.exists():
        for jf in sorted(base.glob("*/*.json")):
            try:
                if jf.resolve().is_relative_to(pred_abs):
                    continue                       # это предсказание, не эталон
            except (ValueError, OSError):
                pass
            try:
                rec = json.loads(jf.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(rec, dict) or "fields" not in rec or "files" not in rec:
                continue
            idx[rec["id"]] = {"fields": rec["fields"], "png": rec["files"]["png"],
                              "doc_type": rec["fields"].get("doc_type", "")}
    return idx


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/api/config")
def get_config():
    cfg = config.load()
    return {"ai_mode": cfg.ai_mode, "model": cfg.model,
            "valid_modes": list(ai_provider._PROVIDERS.keys()),
            "valid_models": config.VALID_MODELS,
            "dataset_dir": str(cfg.dataset_dir()),
            "has_env_key": bool(os.getenv("ANTHROPIC_API_KEY")),
            "onboarded": _SESSION["onboarded"],
            "warnings": cfg.validate()}


@app.post("/api/config")
async def set_config(payload: dict):
    cfg = config.load()
    if "ai_mode" in payload:
        cfg._data["ai_mode"] = payload["ai_mode"]
    if "model" in payload:
        cfg._data["model"] = payload["model"]
    config.save(cfg)
    return {"ok": True, "ai_mode": cfg.ai_mode, "model": cfg.model}


@app.post("/api/set-key")
async def set_key(payload: dict):
    """Принять API-ключ из UI. Хранится ТОЛЬКО в памяти процесса (не в файлах/репо/config.json)."""
    k = (payload.get("api_key") or "").strip()
    _RUNTIME_KEY["api_key"] = k or None
    return {"ok": True, "has_key": bool(_RUNTIME_KEY["api_key"])}


@app.post("/api/onboard")
async def onboard(payload: dict):
    """Завершить онбординг первого запуска: выбрать режим (api/sdk/mock), при api — принять ключ.
    Ключ живёт только в памяти. Помечаем сессию onboarded, чтобы модалка не показывалась до рестарта."""
    mode = payload.get("mode")
    if mode in ("api", "sdk", "mock"):
        cfg = config.load()
        cfg._data["ai_mode"] = mode
        config.save(cfg)
    if mode == "api":
        k = (payload.get("api_key") or "").strip()
        _RUNTIME_KEY["api_key"] = k or None
    _SESSION["onboarded"] = True
    return {"ok": True, "onboarded": True, "ai_mode": mode,
            "has_key": bool(_RUNTIME_KEY["api_key"])}


@app.get("/api/dataset")
def dataset():
    idx = _truth_index()
    items = [{"id": k, "doc_type": v["doc_type"], "png": v["png"]} for k, v in idx.items()]
    return {"count": len(items), "items": items}


@app.get("/api/file")
def get_file(path: str):
    base = config.load().dataset_dir().resolve()
    target = (base / path).resolve()
    if os.path.commonpath([str(base), str(target)]) != str(base):
        raise HTTPException(403, "path outside dataset_dir")
    if not target.exists():
        raise HTTPException(404, "not found")
    return FileResponse(str(target))


@app.post("/api/extract-doc")
async def extract_doc(payload: dict):
    """Извлечь документ из датасета по id и сверить с его ground-truth."""
    did = payload.get("id")
    idx = _truth_index()
    if did not in idx:
        raise HTTPException(404, "unknown document id")
    cfg = config.load()
    png_abs = str(cfg.dataset_dir() / idx[did]["png"])
    key = _RUNTIME_KEY["api_key"]
    fields = await asyncio.to_thread(lambda: extract.extract(png_abs, cfg, api_key=key))
    comparison = batch.compare_one(idx[did]["fields"], fields)
    return {"id": did, "mode": cfg.ai_mode, "model": cfg.model,
            "predicted": fields, "truth": idx[did]["fields"], "comparison": comparison,
            "validation": validate.summary(validate.check(fields))}


@app.post("/api/extract-upload")
async def extract_upload(file: UploadFile = File(...)):
    """Извлечь данные из загруженного файла (ground-truth нет — только JSON)."""
    cfg = config.load()
    suffix = os.path.splitext(file.filename or "")[1] or ".png"
    data = await file.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(data)
        tmp.close()
        key = _RUNTIME_KEY["api_key"]
        fields = await asyncio.to_thread(lambda: extract.extract(tmp.name, cfg, api_key=key))
    finally:
        os.unlink(tmp.name)
    # Для чужого документа ground-truth нет — арифметическая валидация тут единственный
    # автоматический контроль качества извлечения.
    return {"filename": file.filename, "mode": cfg.ai_mode, "model": cfg.model,
            "predicted": fields, "truth": None, "comparison": None,
            "validation": validate.summary(validate.check(fields))}


@app.get("/api/batch")
async def run_batch_stream():
    """Батч по всему датасету со стримингом прогресса; финальное событие — отчёт."""
    cfg = config.load()
    dataset_dir = str(cfg.dataset_dir())
    pred_dir = str(cfg.pred_dir())

    async def event_stream():
        q: queue.Queue = queue.Queue()

        def work():
            try:
                report = batch.run_batch(dataset_dir, pred_dir, cfg=cfg, progress=q.put,
                                         api_key=_RUNTIME_KEY["api_key"])
                q.put({"stage": "report", "report": report})
            except Exception as e:  # noqa: BLE001
                q.put({"stage": "error", "message": f"Ошибка: {e}"})
            finally:
                q.put(None)

        threading.Thread(target=work, daemon=True).start()
        while True:
            event = await asyncio.to_thread(q.get)
            if event is None:
                break
            yield _sse(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/report")
def report():
    cfg = config.load()
    return batch.build_report(str(cfg.dataset_dir()), str(cfg.pred_dir()))


if os.path.isdir(STATIC):
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


def main():
    import uvicorn
    port = int(os.getenv("EXTRACTOR_PORT", "8002"))
    url = f"http://127.0.0.1:{port}"
    print(f"Экстрактор: {url}")
    try:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    except Exception:
        pass
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
