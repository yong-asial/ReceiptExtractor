"""Unit tests for the upload gate: size caps, batch cap, non-image rejection."""
import importlib.util, io, os, sys
from PIL import Image

class _Stub:
    def __init__(self, *a, **k): object.__setattr__(self, "_d", {})
    def __call__(self, *a, **k): return _Stub()
    def __getattr__(self, n): return _Stub()
    def __bool__(self): return False
    def __setitem__(self, k, v): self._d[k] = v
    def __getitem__(self, k): return self._d[k]
    def __contains__(self, k): return k in self._d
    def get(self, k, default=None): return self._d.get(k, default)
    def pop(self, k, default=None): return self._d.pop(k, default)
sys.modules["streamlit"] = _Stub()
sys.modules["ollama"] = _Stub()

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "receipt_app", os.path.join(HERE, os.pardir, "app", "app.py"))
app = importlib.util.module_from_spec(spec); spec.loader.exec_module(app)

class Fake:
    """Stand-in for a Streamlit UploadedFile."""
    def __init__(self, name, raw): self.name, self._raw = name, raw
    @property
    def size(self): return len(self._raw)
    def getvalue(self): return self._raw

def jpeg(w=400, h=600, pad=0):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (240, 240, 240)).save(buf, "JPEG", quality=90)
    return buf.getvalue() + b"\x00" * pad   # pad trails the EOI marker

fails = 0
def check(label, cond):
    global fails
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if not cond: fails += 1

MB = 1024 * 1024
print("1. a normal receipt is accepted")
acc, probs = app.check_uploads([Fake("receipt.jpg", jpeg())])
check("accepted", len(acc) == 1 and acc[0][0] == "receipt.jpg")
check("no complaints", probs == [])

print("2. an image over 10 MB is refused")
acc, probs = app.check_uploads([Fake("huge.jpg", jpeg(pad=11 * MB))])
check("not accepted", acc == [])
check("says why", len(probs) == 1 and "10.0 MB limit" in probs[0])

print("3. just under 10 MB still gets through")
acc, probs = app.check_uploads([Fake("big.jpg", jpeg(pad=9 * MB))])
check("accepted", len(acc) == 1 and probs == [])

print("4. a batch over 20 MB is rejected whole, not trimmed")
batch = [Fake(f"r{i}.jpg", jpeg(pad=7 * MB)) for i in range(3)]   # ~21 MB
acc, probs = app.check_uploads(batch)
check("nothing accepted", acc == [])
check("says why", any("20.0 MB limit for one batch" in p for p in probs))

print("5. a batch just under 20 MB is fine")
batch = [Fake(f"r{i}.jpg", jpeg(pad=6 * MB)) for i in range(3)]   # ~18 MB
acc, probs = app.check_uploads(batch)
check("all three accepted", len(acc) == 3 and probs == [])

print("6. a non-image wearing a .jpg name is refused")
acc, probs = app.check_uploads([Fake("fake.jpg", b"%PDF-1.4\nnot an image")])
check("not accepted", acc == [])
check("says why", "not an image" in probs[0])

print("7. an empty file is refused")
acc, probs = app.check_uploads([Fake("empty.jpg", b"")])
check("not accepted", acc == [] and "is empty" in probs[0])

print("8. an oversized-in-pixels image is refused")
acc, probs = app.check_uploads([Fake("bomb.png", jpeg(w=12000, h=9000))])
check("refused on pixel count", acc == [] and "too large to process" in probs[0])

print("9. one bad file does not sink the good ones")
acc, probs = app.check_uploads([
    Fake("good.jpg", jpeg()), Fake("bad.jpg", b"nope"), Fake("good2.png", jpeg())])
check("two accepted", [n for n, _ in acc] == ["good.jpg", "good2.png"])
check("one complaint", len(probs) == 1)

print("10. an oversized file does not eat the batch budget")
acc, probs = app.check_uploads([
    Fake("huge.jpg", jpeg(pad=15 * MB)), Fake("ok.jpg", jpeg(pad=9 * MB))])
check("the small one still runs", [n for n, _ in acc] == ["ok.jpg"])

print("11. accepted bytes are still readable by prepare_image")
acc, _ = app.check_uploads([Fake("receipt.jpg", jpeg())])
out = app.prepare_image(acc[0][1])
check("re-encodes to a JPEG", out[:2] == b"\xff\xd8")

print("12. human_size")
check("10 MB", app.human_size(10 * MB) == "10.0 MB")
check("840 KB", app.human_size(840 * 1024) == "840 KB")

print("13. upload_signature sorts a mixed set without blowing up")
a, b = Fake("a.jpg", jpeg()), Fake("b.jpg", jpeg())
a.file_id = "abc-123"
check("no TypeError", len(app.upload_signature([a, b])) == 2)
check("empty set", app.upload_signature([]) == ())

print()
print("=== ALL PASSED ===" if not fails else f"=== {fails} FAILED ===")
sys.exit(1 if fails else 0)
