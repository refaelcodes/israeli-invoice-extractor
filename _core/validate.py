# -*- coding: utf-8 -*-
"""Арифметическая валидация извлечённых данных.

Зачем: vision-модель одинаково уверенно возвращает и правильное, и выдуманное число —
confidence она не даёт. Но у финансового документа есть внутренняя арифметика
(сумма позиций = subtotal, subtotal + НДС = total, брутто − удержания = нетто).
Если она не сходится — значит какое-то поле прочитано неверно. Это ДЕШЁВЫЙ и надёжный
детектор ошибок, не требующий ground-truth. Работает и на чужих реальных документах.

Возвращаем КОДЫ (не текст), чтобы UI переводил их на нужный язык.
"""

# Порог מספר הקצאה, продублирован из _generator/fake.py ALLOCATION_THRESHOLD
# (_core не должен зависеть от генератора). Закон меняется — сверять.
ALLOCATION_THRESHOLD = 5000

ERROR = "error"
WARN = "warn"


def _num(x):
    """В число или None. bool -> None (чтобы не считать True за 1)."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        import re
        return float(re.sub(r"[₪,\s]", "", str(x)))
    except Exception:
        return None


def _close(expected, got):
    """Допуск как в evaluate.py для денег: 0.5% относительной или 0.02 абсолютной."""
    return abs(expected - got) <= max(0.02, abs(expected) * 0.005)


def _sum_field(items, key):
    """Сумма числового поля по списку; None если список пуст/не список/нет чисел."""
    if not isinstance(items, list) or not items:
        return None
    vals = [_num(it.get(key)) for it in items if isinstance(it, dict)]
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def _issue(code, severity, expected, got, fields):
    return {"code": code, "severity": severity,
            "expected": round(expected, 2), "got": round(got, 2),
            "diff": round(got - expected, 2), "fields": fields}


def check(fields: dict) -> list:
    """Проверить внутреннюю арифметику документа. [] == всё сходится."""
    if not isinstance(fields, dict):
        return []
    issues = []
    f = fields

    subtotal = _num(f.get("subtotal"))
    vat_amount = _num(f.get("vat_amount"))
    vat_rate = _num(f.get("vat_rate"))
    total = _num(f.get("total"))

    # 1) сумма позиций == subtotal
    li_sum = _sum_field(f.get("line_items"), "line_total")
    if li_sum is not None and subtotal is not None and not _close(subtotal, li_sum):
        issues.append(_issue("LINE_ITEMS_SUM", ERROR, subtotal, li_sum, ["line_items[].line_total", "subtotal"]))

    # 2) subtotal + НДС == total
    if subtotal is not None and vat_amount is not None and total is not None \
            and not _close(total, subtotal + vat_amount):
        issues.append(_issue("VAT_TOTAL", ERROR, total, subtotal + vat_amount, ["subtotal", "vat_amount", "total"]))

    # 2b) документ БЕЗ НДС: total должен равняться subtotal.
    # Иначе проверка (2) молча пропускается и ошибка в total остаётся незамеченной —
    # ровно это случилось на реальном чеке Anthropic (USD, без НДС).
    # Побочный плюс: ловит и случай, когда НДС на бланке есть, а модель его не извлекла.
    no_vat = vat_amount is None or abs(vat_amount) < 0.005
    if no_vat and subtotal is not None and total is not None and not _close(total, subtotal):
        issues.append(_issue("TOTAL_NO_VAT", ERROR, total, subtotal, ["subtotal", "total", "vat_amount"]))

    # 3) subtotal * ставка == НДС
    if subtotal is not None and vat_rate is not None and vat_amount is not None \
            and not _close(vat_amount, subtotal * vat_rate):
        issues.append(_issue("VAT_RATE_CALC", WARN, vat_amount, subtotal * vat_rate,
                             ["subtotal", "vat_rate", "vat_amount"]))

    # 4) позиция: |qty * unit_price| == |line_total|
    # По МОДУЛЮ: в кредит-ноте (חשבונית זיכוי) line_total отрицательный, а qty/unit_price
    # положительные — знак там несёт смысл документа, а не арифметическую ошибку.
    # Согласованность знаков ловит LINE_ITEMS_SUM (сумма со знаком против subtotal).
    for i, it in enumerate(f.get("line_items") or []):
        if not isinstance(it, dict):
            continue
        q, p, lt = _num(it.get("quantity")), _num(it.get("unit_price")), _num(it.get("line_total"))
        if None not in (q, p, lt) and not _close(abs(lt), abs(q * p)):
            issues.append(_issue("LINE_ITEM_MATH", WARN, lt, q * p,
                                 [f"line_items[{i}].quantity", f"line_items[{i}].unit_price",
                                  f"line_items[{i}].line_total"]))

    # 5) payslip: брутто − удержания == нетто
    gross = _num(f.get("gross"))
    total_ded = _num(f.get("total_deductions"))
    net = _num(f.get("net_pay"))
    if None not in (gross, total_ded, net) and not _close(net, gross - total_ded):
        issues.append(_issue("PAYSLIP_NET", ERROR, net, gross - total_ded,
                             ["gross", "total_deductions", "net_pay"]))

    earn_sum = _sum_field(f.get("earnings"), "amount")
    if earn_sum is not None and gross is not None and not _close(gross, earn_sum):
        issues.append(_issue("EARNINGS_SUM", WARN, gross, earn_sum, ["earnings[].amount", "gross"]))

    ded_sum = _sum_field(f.get("deductions"), "amount")
    if ded_sum is not None and total_ded is not None and not _close(total_ded, ded_sum):
        issues.append(_issue("DEDUCTIONS_SUM", WARN, total_ded, ded_sum,
                             ["deductions[].amount", "total_deductions"]))

    # 6) банк: баланс последней транзакции == closing_balance
    txs = f.get("transactions")
    closing = _num(f.get("closing_balance"))
    if isinstance(txs, list) and txs and closing is not None:
        last_bal = _num(txs[-1].get("balance")) if isinstance(txs[-1], dict) else None
        if last_bal is not None and not _close(closing, last_bal):
            issues.append(_issue("CLOSING_BALANCE", ERROR, closing, last_bal,
                                 ["transactions[-1].balance", "closing_balance"]))

    # 7) бизнес-правило: מספר הקצאה обязателен при subtotal >= порога
    if subtotal is not None and abs(subtotal) >= ALLOCATION_THRESHOLD \
            and str(f.get("doc_type", "")).startswith("חשבונית מס") \
            and not f.get("allocation_number"):
        issues.append({"code": "ALLOCATION_MISSING", "severity": WARN,
                       "expected": ALLOCATION_THRESHOLD, "got": abs(subtotal), "diff": 0,
                       "fields": ["allocation_number", "subtotal"]})

    # 8) «пустое извлечение»: ни одного денежного якоря.
    # Арифметические проверки выше молчат, когда проверять нечего — а именно так выглядит
    # документ, прочитанный с плохого/мелкого скана (эмпирически: <~600px по длинной стороне
    # модель возвращает почти одни null). Без этой проверки такой случай выглядел бы как «всё ок».
    anchors = [subtotal, total, vat_amount, gross, net,
               _num(f.get("amount")), _num(f.get("closing_balance"))]
    if all(a is None for a in anchors):
        issues.append({"code": "NO_AMOUNTS", "severity": ERROR,
                       "expected": 0, "got": 0, "diff": 0,
                       "fields": ["subtotal", "total", "amount", "net_pay", "closing_balance"]})

    return issues


def summary(issues: list) -> dict:
    """Свод для UI/CLI: ok=True если нет ошибок уровня error."""
    errors = [i for i in issues if i["severity"] == ERROR]
    warns = [i for i in issues if i["severity"] == WARN]
    return {"ok": not errors, "errors": len(errors), "warnings": len(warns),
            "needs_review": bool(issues), "issues": issues}
