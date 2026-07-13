# -*- coding: utf-8 -*-
"""Обратная совместимость: делегирует в batch.run_batch (логика переехала туда).

    python run_all.py --dataset DIR --pred OUTDIR [--mode api|sdk|mock]
"""
import os
import sys

import batch


if __name__ == "__main__":
    a = sys.argv
    ds = a[a.index("--dataset") + 1] if "--dataset" in a else None
    pd = a[a.index("--pred") + 1] if "--pred" in a else "pred"
    md = a[a.index("--mode") + 1] if "--mode" in a else None
    if not ds:
        print(__doc__)
        sys.exit(1)
    rep = batch.run_batch(os.path.abspath(ds), os.path.abspath(pd), mode=md,
                          progress=lambda e: print("  " + e.get("message", "")))
    print(f"\n=== ТОЧНОСТЬ: {100*rep['overall_accuracy']:.1f}% "
          f"({rep['docs_checked']} док., {rep['fields_total']} полей) ===")
    for w in rep["weakest_fields"][:12]:
        print(f"  {w['field']:34s} {100*w['accuracy']:5.1f}%  ({w['correct']}/{w['total']})")
