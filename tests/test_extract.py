"""Score the extraction against ground truth, for one or more models."""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "app"))

import reader, settings, tidy, uploads

with open(os.path.join(HERE, "receipts", "ground_truth.json")) as fh:
    cases = json.load(fh)

models = sys.argv[1:] or ["qwen2.5vl:7b"]
report = {}

for model in models:
    print(f"\n{'='*70}\nMODEL: {model}\n{'='*70}")
    hits = misses = 0
    rows = []
    for case in cases:
        path = os.path.join(HERE, "receipts", case["file"])
        with open(path, "rb") as fh:
            raw = fh.read()

        t0 = time.time()
        try:
            got = reader.extract(uploads.prepare_image(raw), model)
            err = None
        except Exception as exc:
            got, err = None, f"{type(exc).__name__}: {exc}"
        elapsed = time.time() - t0

        print(f"\n--- {case['file']}  ({elapsed:.1f}s)")
        if err:
            print(f"    FAILED: {err}")
            misses += len(case["truth"])
            rows.append({"file": case["file"], "error": err})
            continue

        truth = case["truth"]
        for field in settings.FIELDS:
            want, have = truth[field], got[field]
            # Payment method is free text; accept a substring match either way.
            if field == "Payment Method":
                ok = want.lower() in have.lower() or have.lower() in want.lower()
            elif field in ("Subtotal", "Tax", "Total Amount"):
                try:
                    ok = abs(float(want) - float(have)) < 0.011
                except ValueError:
                    ok = want == have
            else:
                ok = want.strip().lower() == have.strip().lower()

            hits += ok
            misses += not ok
            mark = "ok  " if ok else "MISS"
            note = "" if ok else f"   (want {want!r})"
            print(f"    [{mark}] {field:<16} = {have!r}{note}")

        flags = tidy.flag_issues(got)
        print(f"    review flags: {flags or '(none)'}")
        rows.append({"file": case["file"], "got": got, "flags": flags})

    total = hits + misses
    pct = 100 * hits / total if total else 0
    print(f"\n>>> {model}: {hits}/{total} fields correct ({pct:.0f}%)")
    report[model] = {"hits": hits, "total": total, "pct": round(pct), "rows": rows}

with open(os.path.join(HERE, "test_report.json"), "w") as fh:
    json.dump(report, fh, indent=2)

print(f"\n{'='*70}\nSUMMARY")
for model, r in report.items():
    print(f"  {model:<24} {r['hits']:>2}/{r['total']} ({r['pct']}%)")
