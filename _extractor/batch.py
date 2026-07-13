# -*- coding: utf-8 -*-
"""Батч-прогон датасета + структурированный отчёт точности (для GUI и CLI).

Пришёл на смену run_all.py: логика вынесена в функции с колбэком прогресса (вместо print),
а сверка возвращает СТРУКТУРУ (не только текст) — чтобы GUI мог подсветить поля.
Сама метрика — из evaluate.py без изменений (score_doc / flatten / leaf_equal).
"""
import os
import sys
import re
import json
import glob
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for p in (_HERE, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import extract          # noqa: E402
import evaluate         # noqa: E402  (score_doc, flatten, leaf_equal)
from _core import config  # noqa: E402


def _noop(_e):
    pass


def compare_one(truth_fields, pred_fields):
    """Сверка одного документа -> {accuracy, correct, total, fields:[{path, ok, truth, pred}]}."""
    c, n, per = evaluate.score_doc(truth_fields, pred_fields)
    tflat = evaluate.flatten(truth_fields)
    pflat = evaluate.flatten(pred_fields)
    fields = [{"path": path, "ok": ok, "truth": tflat.get(path), "pred": pflat.get(path)}
              for path, ok in per.items()]
    return {"accuracy": (c / n if n else 0.0), "correct": c, "total": n, "fields": fields}


def build_report(dataset_dir, pred_dir):
    """Сводный отчёт по всем документам, у которых есть предсказание. Сеть не нужна."""
    truth_files = sorted(glob.glob(os.path.join(dataset_dir, "**", "*.json"), recursive=True))
    # pred_dir может лежать ВНУТРИ dataset_dir (напр. dataset_dir=".") — не принимать
    # файлы предсказаний за эталон, иначе они сверяются сами с собой и раздувают точность.
    pred_abs = os.path.abspath(pred_dir)
    total_c = total_n = 0
    per_doc = []
    field_stats = {}
    for tf in truth_files:
        if os.path.commonpath([pred_abs, os.path.abspath(tf)]) == pred_abs:
            continue                 # файл внутри pred_dir — это предсказание, не эталон
        rec = json.load(open(tf, encoding="utf-8"))
        if "fields" not in rec:      # пропустить сводный dataset_ground_truth.json
            continue
        did = rec.get("id") or os.path.splitext(os.path.basename(tf))[0]
        pf = os.path.join(pred_dir, did + ".json")
        if not os.path.exists(pf):
            per_doc.append({"id": did, "accuracy": None, "detail": None})
            continue
        pred = json.load(open(pf, encoding="utf-8"))
        pred = pred.get("fields", pred)
        detail = compare_one(rec["fields"], pred)
        total_c += detail["correct"]
        total_n += detail["total"]
        per_doc.append({"id": did, "accuracy": detail["accuracy"], "detail": detail})
        for f in detail["fields"]:
            key = re.sub(r"\[\d+\]", "[]", f["path"])
            s = field_stats.setdefault(key, [0, 0])
            s[1] += 1
            s[0] += int(f["ok"])
    weakest = sorted(
        ({"field": k, "accuracy": c / n, "correct": c, "total": n}
         for k, (c, n) in field_stats.items()),
        key=lambda x: x["accuracy"])
    return {
        "overall_accuracy": (total_c / total_n if total_n else 0.0),
        "docs_checked": sum(1 for d in per_doc if d["accuracy"] is not None),
        "fields_total": total_n,
        "per_doc": per_doc,
        "weakest_fields": weakest,
    }


def run_batch(dataset_dir, pred_dir, cfg=None, mode=None, progress=None):
    """Извлечь все PNG датасета -> записать pred/<id>.json -> вернуть build_report()."""
    cfg = cfg or config.load()
    progress = progress or _noop
    os.makedirs(pred_dir, exist_ok=True)
    pngs = sorted(glob.glob(os.path.join(dataset_dir, "**", "*.png"), recursive=True))
    total = len(pngs)
    progress({"stage": "start", "current": 0, "total": total, "message": f"Старт батча: {total} PNG"})
    for i, png in enumerate(pngs, 1):
        did = os.path.splitext(os.path.basename(png))[0]
        try:
            fields = extract.extract(png, cfg=cfg, mode=mode)
            json.dump({"id": did, "fields": fields},
                      open(os.path.join(pred_dir, did + ".json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            progress({"stage": "doc", "current": i, "total": total, "id": did, "ok": True,
                      "message": f"[{i}/{total}] OK {did}"})
        except Exception as e:
            progress({"stage": "doc", "current": i, "total": total, "id": did, "ok": False,
                      "message": f"[{i}/{total}] FAIL {did}: {e}"})
            traceback.print_exc()
    report = build_report(dataset_dir, pred_dir)
    progress({"stage": "done", "current": total, "total": total,
              "message": f"Готово. Точность: {100*report['overall_accuracy']:.1f}%"})
    return report


if __name__ == "__main__":
    a = sys.argv
    ds = a[a.index("--dataset") + 1] if "--dataset" in a else None
    pd = a[a.index("--pred") + 1] if "--pred" in a else "pred"
    md = a[a.index("--mode") + 1] if "--mode" in a else None
    if not ds:
        print(__doc__)
        sys.exit(1)
    rep = run_batch(os.path.abspath(ds), os.path.abspath(pd), mode=md,
                    progress=lambda e: print("  " + e.get("message", "")))
    print(f"\n=== ТОЧНОСТЬ: {100*rep['overall_accuracy']:.1f}% "
          f"({rep['docs_checked']} док., {rep['fields_total']} полей) ===")
    for w in rep["weakest_fields"][:12]:
        print(f"  {w['field']:34s} {100*w['accuracy']:5.1f}%  ({w['correct']}/{w['total']})")
