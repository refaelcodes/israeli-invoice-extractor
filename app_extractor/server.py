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
from _core import config, ai_provider, validate, paths  # noqa: E402

app = FastAPI(title="Israeli Docs — Экстрактор")
STATIC = os.path.join(_HERE, "static")

# Локальное хранилище подключений к Claude (git-ignored, в репозиторий НЕ попадает — на машине
# пользователя). Пишется ТОЛЬКО когда стоит галочка «запомнить». В памяти процесса:
#   api_key — ключ для режима api;  sdk — пользователь подтвердил режим sdk (авторизация берётся из
# системного `claude login`). Активный режим (api/sdk/mock) хранится отдельно в config.json.
_CREDS_PATH = paths.PROJECT_ROOT / ".local_credentials.json"
_RUNTIME = {"api_key": None, "sdk": False}


def _read_saved() -> dict:
    if not _CREDS_PATH.exists():
        return {}
    try:
        return json.loads(_CREDS_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _write_saved(d: dict) -> None:
    d = {k: v for k, v in d.items() if v}     # пустое/False не храним
    if d:
        _CREDS_PATH.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    else:
        try:
            _CREDS_PATH.unlink()
        except FileNotFoundError:
            pass


def _apply_mode(mode: str) -> None:
    """Записать активный режим в config.json, чтобы извлечение брало нужный провайдер."""
    if mode in ("api", "sdk", "mock"):
        cfg = config.load()
        cfg._data["ai_mode"] = mode
        config.save(cfg)


def _connected(mode: str) -> bool:
    """Подключён ли режим: mock — всегда; api — есть ключ; sdk — подтверждён пользователем."""
    if mode == "mock":
        return True
    if mode == "api":
        return bool(_RUNTIME["api_key"])
    if mode == "sdk":
        return bool(_RUNTIME["sdk"])
    return False


# Восстановить сохранённые подключения при старте (активный режим берётся из config.json как есть).
_saved = _read_saved()
_RUNTIME["api_key"] = _saved.get("api_key")
_RUNTIME["sdk"] = bool(_saved.get("sdk"))


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
    # no-cache: чтобы после git pull браузер не показывал устаревший UI из кэша
    return FileResponse(os.path.join(STATIC, "index.html"),
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/api/config")
def get_config():
    cfg = config.load()
    return {"ai_mode": cfg.ai_mode, "model": cfg.model,
            "valid_modes": list(ai_provider._PROVIDERS.keys()),
            "valid_models": config.VALID_MODELS,
            "dataset_dir": str(cfg.dataset_dir()),
            "connected": _connected(cfg.ai_mode),
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


@app.post("/api/connect")
async def connect(payload: dict):
    """Подключить режим:
      api — принять СВОЙ ключ Anthropic (обязателен);
      sdk — БЕЗ токена: использует уже выполненный на этой машине `claude login` (подписку Claude).
    Делает режим активным. Секрет пишется на диск ТОЛЬКО при remember=true (иначе живёт лишь в памяти
    процесса — при рестарте снова попросит). Файл кредов — в .gitignore, в репозиторий не попадает."""
    mode = payload.get("mode")
    if mode not in ("api", "sdk"):
        raise HTTPException(400, "mode must be api or sdk")
    remember = bool(payload.get("remember"))
    saved = _read_saved()
    if mode == "api":
        key = (payload.get("api_key") or "").strip() or None
        if not key:
            raise HTTPException(400, "api_key required")
        _RUNTIME["api_key"] = key
        if remember:
            saved["api_key"] = key
        else:
            saved.pop("api_key", None)
    else:  # sdk
        _RUNTIME["sdk"] = True
        if remember:
            saved["sdk"] = True
        else:
            saved.pop("sdk", None)
    _write_saved(saved)
    _apply_mode(mode)
    return {"ok": True, "ai_mode": mode, "connected": True, "remembered": remember}


@app.post("/api/disconnect")
async def disconnect(payload: dict = None):
    """Отключить режим (api или sdk): стереть его подключение из памяти и с диска. Активный режим
    остаётся тем же -> кнопка станет «Подключить». Режим mock отключать нечего."""
    cfg = config.load()
    mode = (payload or {}).get("mode") or cfg.ai_mode
    saved = _read_saved()
    if mode == "api":
        _RUNTIME["api_key"] = None
        saved.pop("api_key", None)
    elif mode == "sdk":
        _RUNTIME["sdk"] = False
        saved.pop("sdk", None)
    _write_saved(saved)
    return {"ok": True, "ai_mode": mode, "connected": _connected(mode)}


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
    key = _RUNTIME["api_key"]
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
        key = _RUNTIME["api_key"]
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
                                         api_key=_RUNTIME["api_key"])
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
