# -*- coding: utf-8 -*-
"""
Оценка точности экстрактора: сравнивает предсказанный JSON с ground-truth
ПО КАЖДОМУ ПОЛЮ и считает точность. Сеть не нужна.

Запуск:
    python3 evaluate.py  --truth  DATASET_DIR  --pred  PRED_DIR
    # truth: рядом с документами лежат <id>.json (наш ground-truth, поле .fields)
    # pred:  <id>.json с предсказанными полями (вывод extract.py)

Метрика: доля листовых полей, совпавших с эталоном. Числа — с допуском,
строки — нормализованное сравнение, списки — поэлементно по позиции.
Учитываются только поля, присутствующие в ground-truth (лишние предсказанные игнорируются).
"""
import os, sys, json, glob, re


def _num(x):
    try:
        if isinstance(x, bool): return None
        if isinstance(x, (int, float)): return float(x)
        s = re.sub(r"[₪,\s]", "", str(x))
        return float(s)
    except Exception:
        return None


def _norm_str(x):
    return re.sub(r"\s+", " ", str(x).strip()).lower()


AMOUNT_FIELDS = {"subtotal", "vat_amount", "total", "unit_price", "line_total", "gross",
                 "net_pay", "amount", "closing_balance", "balance", "debit", "credit",
                 "quantity", "vat_rate"}


def leaf_equal(truth, pred, leaf_name=""):
    if truth is None:
        return pred is None
    if isinstance(truth, bool):
        return bool(truth) == bool(pred)
    # числовой допуск ТОЛЬКО для денежных/количественных полей;
    # идентификаторы (id, номера, מספר הקצאה, счёт) сверяем строго.
    if leaf_name in AMOUNT_FIELDS:
        tn, pn = _num(truth), _num(pred)
        if tn is not None and pn is not None:
            return abs(tn - pn) <= max(0.01, abs(tn) * 0.005)
    tn, pn = _num(truth), _num(pred)
    if tn is not None and pn is not None:
        return tn == pn                       # точное числовое равенство для ID-чисел
    return _norm_str(truth) == _norm_str(pred)


def flatten(d, prefix=""):
    """dict/list -> {путь: значение-лист}."""
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = d
    return out


def score_doc(truth_fields, pred_fields):
    t = flatten(truth_fields)
    p = flatten(pred_fields)
    per = {}
    for path, tv in t.items():
        leaf = re.sub(r"\[\d+\]", "", path).split(".")[-1]
        per[path] = leaf_equal(tv, p.get(path, None), leaf)
    correct = sum(per.values())
    return correct, len(per), per


def main(truth_dir, pred_dir):
    truth_files = glob.glob(os.path.join(truth_dir, "**", "*.json"), recursive=True)
    total_c = total_n = 0
    field_stats = {}   # имя_поля(без индексов) -> [correct, total]
    per_doc = []
    checked = 0
    for tf in sorted(truth_files):
        rec = json.load(open(tf, encoding="utf-8"))
        if "fields" not in rec:      # пропускаем сводный файл и прочее
            continue
        did = rec.get("id") or os.path.splitext(os.path.basename(tf))[0]
        pf = os.path.join(pred_dir, did + ".json")
        if not os.path.exists(pf):
            per_doc.append((did, None)); continue
        pred = json.load(open(pf, encoding="utf-8"))
        pred = pred.get("fields", pred)
        c, n, per = score_doc(rec["fields"], pred)
        total_c += c; total_n += n; checked += 1
        per_doc.append((did, c / n if n else 0))
        for path, ok in per.items():
            key = re.sub(r"\[\d+\]", "[]", path)
            s = field_stats.setdefault(key, [0, 0]); s[1] += 1; s[0] += int(ok)

    print(f"=== ТОЧНОСТЬ ЭКСТРАКТОРА ===")
    print(f"Документов сверено: {checked} | полей: {total_n} | "
          f"общая точность: {100*total_c/total_n:.1f}%\n" if total_n else "нет данных\n")
    print("По документам:")
    for did, acc in per_doc:
        print(f"  {did:28s} {'—' if acc is None else f'{100*acc:5.1f}%'}")
    print("\nСлабейшие поля (точность по возрастанию):")
    ranked = sorted(field_stats.items(), key=lambda kv: kv[1][0]/kv[1][1] if kv[1][1] else 1)
    for key, (c, n) in ranked[:12]:
        print(f"  {key:34s} {100*c/n:5.1f}%  ({c}/{n})")
    return total_c, total_n


if __name__ == "__main__":
    a = sys.argv
    truth = a[a.index("--truth")+1] if "--truth" in a else None
    pred = a[a.index("--pred")+1] if "--pred" in a else None
    if not truth or not pred:
        print(__doc__); sys.exit(1)
    main(truth, pred)
