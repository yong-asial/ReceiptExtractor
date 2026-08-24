"""Score app.py's extraction against ground truth, for one or more models."""
import importlib.util, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, os.pardir, "app", "app.py")

# Import app.py without executing its Streamlit UI: stub out streamlit first.
class _Stub:
    """Stand-in for streamlit so app.py can be imported without a UI.

    Backed by a real dict so st.session_state assignment works.
    """
    def __init__(self, *a, **k): object.__setattr__(self, "_d", {})
    def __call__(self, *a, **k): return _Stub()
    def __getattr__(self, name): return _Stub()
    def __setitem__(self, k, v): self._d[k] = v
    def __getitem__(self, k): return self._d[k]
    def __contains__(self, k): return k in self._d
    def get(self, k, default=None): return self._d.get(k, default)
    def pop(self, k, default=None): return self._d.pop(k, default)
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __bool__(self): return False
    def __iter__(self): return iter([])

sys.modules["streamlit"] = _Stub()

spec = importlib.util.spec_from_file_location("receipt_app", APP)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

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
            got = app.extract(app.prepare_image(raw), model)
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
        for field in app.FIELDS:
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

        flags = app.flag_issues(got)
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
