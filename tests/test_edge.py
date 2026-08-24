"""Edge cases: non-receipt input, determinism, amount-cleaning unit tests."""
import io, json, os, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "app"))

import reader, settings, tidy, uploads

MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5vl:7b"

print("="*66)
print("1. clean_amount() unit tests")
print("="*66)
cases = [
    ("$1,234.56", "1234.56"), ("EUR 1.725,50", "1725.50"), ("Y 1,298", "1298"),
    ("1,50", "1.50"), ("44.00", "44.00"), ("Not Found", "Not Found"),
    ("", "Not Found"), (None, "Not Found"), ("n/a", "Not Found"),
    ("-25.00", "-25.00"), ("$0.00", "0.00"),
    ("12,345,678.90", "12345678.90"), ("¥980", "980"),
    ("¥1,298", "1298"), ("¥803,000", "803000"), ("1,180円", "1180"),
    ("1.234", "1.234"),  # ambiguous: left alone, flagged for review instead
]
bad = 0
for raw, want in cases:
    got = tidy.clean_amount(raw)
    ok = got == want
    bad += not ok
    print(f"  [{'ok  ' if ok else 'MISS'}] {raw!r:<18} -> {got!r}" + ("" if ok else f"  (want {want!r})"))
print(f"  => {len(cases)-bad}/{len(cases)} passed")

print("\n" + "="*66)
print("2. parse_json() robustness")
print("="*66)
snippets = [
    '{"Vendor Name": "A"}',
    '```json\n{"Vendor Name": "A"}\n```',
    '```\n{"Vendor Name": "A"}\n```',
    'Here is the data:\n{"Vendor Name": "A"}\nHope that helps!',
    '  {"Vendor Name": "A"}  ',
]
bad2 = 0
for s in snippets:
    try:
        got = reader.parse_json(s)
        ok = got.get("Vendor Name") == "A"
    except Exception as e:
        ok, got = False, e
    bad2 += not ok
    print(f"  [{'ok  ' if ok else 'MISS'}] {s[:44]!r:<48} -> {got}")
print(f"  => {len(snippets)-bad2}/{len(snippets)} passed")

print("\n" + "="*66)
print("3. flag_issues() catches bad arithmetic / missing fields")
print("="*66)
checks = [
    ({"Total Amount":"100.00","Date":"2024-01-01","Subtotal":"90.00","Tax":"10.00"}, ""),
    ({"Total Amount":"100.00","Date":"2024-01-01","Subtotal":"90.00","Tax":"5.00"}, "subtotal + tax != total"),
    ({"Total Amount":"Not Found","Date":"2024-01-01","Subtotal":"1","Tax":"1"}, "no total"),
    ({"Total Amount":"5","Date":"Not Found","Subtotal":"x","Tax":"x"}, "no date"),
    ({"Total Amount":"5","Date":"03/14/2024","Subtotal":"x","Tax":"x"}, "odd date format"),
    ({"Total Amount":"1.234","Date":"2024-01-01","Subtotal":"x","Tax":"x"},
     "check separator in Total Amount"),
]
bad3 = 0
for row, want in checks:
    got = tidy.flag_issues(row)
    ok = got == want
    bad3 += not ok
    print(f"  [{'ok  ' if ok else 'MISS'}] {got!r:<28}" + ("" if ok else f" (want {want!r})"))
print(f"  => {len(checks)-bad3}/{len(checks)} passed")

print("\n" + "="*66)
print("3b. clean_date() across locales")
print("="*66)
dates = [
    ("2024-03-14", "2024-03-14"), ("2024/11/05", "2024-11-05"),
    ("06-30-2024", "2024-06-30"), ("22.07.2024", "2024-07-22"),
    ("14 Mar 2024", "2024-03-14"), ("Mar 14, 2024", "2024-03-14"),
    ("2024年11月5日", "2024-11-05"), ("2024年8月15日", "2024-08-15"),
    ("2024 年 11 月 5 日", "2024-11-05"), ("2024年11月5日(火)", "2024-11-05"),
    ("06/07/2024", "06/07/2024"),   # ambiguous: left verbatim on purpose
    ("Not Found", "Not Found"), (None, "Not Found"), ("gibberish", "gibberish"),
]
bad3b = 0
for raw, want in dates:
    got = tidy.clean_date(raw); ok = got == want; bad3b += not ok
    print(f"  [{'ok  ' if ok else 'MISS'}] {str(raw):<20} -> {got!r}" + ("" if ok else f"  (want {want!r})"))
print(f"  => {len(dates)-bad3b}/{len(dates)} passed")

print("\n" + "="*66)
print("4. Non-receipt image: does it hallucinate or say Not Found?")
print("="*66)
img = Image.new("RGB", (500, 340), (250, 250, 252))
d = ImageDraw.Draw(img)
f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Courier New.ttf", 20)
d.text((40, 130), "Team offsite photo\n(no receipt here)", font=f, fill=(30, 30, 30))
d.ellipse([340, 60, 440, 160], fill=(120, 170, 220))
buf = io.BytesIO(); img.save(buf, format="JPEG"); blank = buf.getvalue()
try:
    got = reader.extract(uploads.prepare_image(blank), MODEL)
    for k, v in got.items():
        print(f"    {k:<16} = {v!r}")
    invented = [k for k, v in got.items() if k in ("Total Amount","Subtotal","Tax") and v != "Not Found"]
    print(f"  => invented amounts: {invented or 'none'}  flags: {tidy.flag_issues(got)!r}")
except Exception as e:
    print(f"  raised {type(e).__name__}: {e}")

print("\n" + "="*66)
print(f"5. Determinism: same receipt 3x on {MODEL}")
print("="*66)
with open(os.path.join(HERE, "receipts", "receipt_us_cafe.jpg"), "rb") as fh:
    raw = fh.read()
seen = []
for i in range(3):
    r = reader.extract(uploads.prepare_image(raw), MODEL)
    seen.append(json.dumps(r, sort_keys=True))
    print(f"  run {i+1}: total={r['Total Amount']} date={r['Date']} vendor={r['Vendor Name']}")
print(f"  => identical across runs: {len(set(seen)) == 1}")

print("\n" + "="*66)
print("6. prepare_image(): downscaling + PNG/alpha handling")
print("="*66)
big = Image.new("RGBA", (4000, 3000), (255, 0, 0, 128))
b = io.BytesIO(); big.save(b, format="PNG")
out = uploads.prepare_image(b.getvalue())
w, h = Image.open(io.BytesIO(out)).size
print(f"  4000x3000 RGBA PNG -> {w}x{h} JPEG, {len(b.getvalue())//1024}KB -> {len(out)//1024}KB")
print(f"  => long edge capped at {settings.MAX_EDGE}: {max(w,h) == settings.MAX_EDGE}")
