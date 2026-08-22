"""Generate Japanese-language receipt images and merge them into ground_truth.json.

Idempotent: re-running replaces its own cases rather than duplicating them.
"""
import json, os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "receipts")
JP = "/System/Library/Fonts/Hiragino Sans GB.ttc"   # W3 regular, W6 bold
JP_IDX, JP_BOLD_IDX = 0, 2

_cache = {}
def font(size, bold=False):
    key = (size, bold)
    if key not in _cache:
        _cache[key] = ImageFont.truetype(JP, size, index=JP_BOLD_IDX if bold else JP_IDX)
    return _cache[key]


def render(name, lines, width=560, pad=36, bg=(253, 252, 250)):
    """lines: (kind, ...) tuples.

    ("t", text, size, bold, align)  - a single run of text
    ("kv", label, value, size, bold) - label left, value right-aligned
    ("hr",)                          - horizontal rule
    ("sp", px)                       - vertical space
    """
    # Measure first so the canvas is exactly tall enough.
    h = pad
    for ln in lines:
        if ln[0] == "t":   h += ln[2] + 10
        elif ln[0] == "kv": h += ln[3] + 10
        elif ln[0] == "hr": h += 16
        elif ln[0] == "sp": h += ln[1]
    img = Image.new("RGB", (width, h + pad), bg)
    d = ImageDraw.Draw(img)

    y = pad
    for ln in lines:
        if ln[0] == "hr":
            d.line([(pad, y + 7), (width - pad, y + 7)], fill=(140, 140, 145), width=1)
            y += 16
        elif ln[0] == "sp":
            y += ln[1]
        elif ln[0] == "t":
            _, text, size, bold, align = ln
            f = font(size, bold)
            w = d.textlength(text, font=f)
            x = {"l": pad, "c": (width - w) / 2, "r": width - pad - w}[align]
            d.text((x, y), text, font=f, fill=(20, 20, 22))
            y += size + 10
        elif ln[0] == "kv":
            _, label, value, size, bold = ln
            f = font(size, bold)
            d.text((pad, y), label, font=f, fill=(20, 20, 22))
            vw = d.textlength(value, font=f)
            d.text((width - pad - vw, y), value, font=f, fill=(20, 20, 22))
            y += size + 10

    path = os.path.join(OUT, name)
    img.save(path, quality=95)
    print(f"  {name}  {img.size}")
    return path


cases = []

# --- 1. Retail receipt (領収書) from a convenience store --------------------
render("receipt_ja_konbini.jpg", [
    ("t", "領収書", 26, True, "c"),
    ("sp", 6),
    ("t", "株式会社サクラマート", 19, True, "c"),
    ("t", "〒150-0043 東京都渋谷区道玄坂1-2-3", 13, False, "c"),
    ("t", "TEL: 03-1234-5678", 13, False, "c"),
    ("t", "登録番号: T1234567890123", 13, False, "c"),
    ("hr",),
    ("t", "2024年11月5日 19:42", 15, False, "l"),
    ("t", "レジNo. 000517", 15, False, "l"),
    ("hr",),
    ("kv", "おにぎり(鮭) ×2", "¥320", 15, False),
    ("kv", "緑茶 500ml ×1", "¥180", 15, False),
    ("kv", "弁当セット ×1", "¥680", 15, False),
    ("hr",),
    ("kv", "小計", "¥1,180", 15, False),
    ("kv", "消費税(10%)", "¥118", 15, False),
    ("kv", "合計", "¥1,298", 18, True),
    ("hr",),
    ("kv", "現金", "¥1,500", 15, False),
    ("kv", "お釣り", "¥202", 15, False),
    ("sp", 8),
    ("t", "ありがとうございました", 14, False, "c"),
])
cases.append({
    "file": "receipt_ja_konbini.jpg",
    "truth": {"Vendor Name": "株式会社サクラマート", "Date": "2024-11-05",
              "Invoice Number": "000517", "Subtotal": "1180", "Tax": "118",
              "Total Amount": "1298", "Currency": "JPY",
              "Payment Method": "現金"},
})

# --- 2. Business invoice (請求書) -------------------------------------------
render("invoice_ja_design.jpg", [
    ("t", "請求書", 27, True, "c"),
    ("sp", 10),
    ("kv", "請求書番号: 2024-JP-0312", "", 14, False),
    ("kv", "発行日: 2024年8月15日", "", 14, False),
    ("kv", "お支払期限: 2024年9月30日", "", 14, False),
    ("sp", 10),
    ("t", "株式会社青空デザイン", 19, True, "r"),
    ("t", "〒106-0032 東京都港区六本木3-4-5", 13, False, "r"),
    ("t", "登録番号: T9876543210987", 13, False, "r"),
    ("hr",),
    ("t", "件名: ウェブサイト制作費", 15, False, "l"),
    ("hr",),
    ("kv", "デザイン費", "¥450,000", 15, False),
    ("kv", "コーディング費", "¥280,000", 15, False),
    ("hr",),
    ("kv", "小計", "¥730,000", 15, False),
    ("kv", "消費税(10%)", "¥73,000", 15, False),
    ("kv", "御請求金額", "¥803,000", 19, True),
    ("hr",),
    ("t", "お支払方法: 銀行振込", 15, False, "l"),
    ("t", "みずほ銀行 六本木支店 普通 1234567", 13, False, "l"),
], width=600)
cases.append({
    "file": "invoice_ja_design.jpg",
    "truth": {"Vendor Name": "株式会社青空デザイン", "Date": "2024-08-15",
              "Invoice Number": "2024-JP-0312", "Subtotal": "730000",
              "Tax": "73000", "Total Amount": "803000", "Currency": "JPY",
              "Payment Method": "銀行振込"},
})

# --- merge into the shared ground truth, replacing our own entries ----------
gt_path = os.path.join(OUT, "ground_truth.json")
existing = []
if os.path.exists(gt_path):
    with open(gt_path, encoding="utf-8") as fh:
        existing = json.load(fh)
mine = {c["file"] for c in cases}
merged = [c for c in existing if c["file"] not in mine] + cases
with open(gt_path, "w", encoding="utf-8") as fh:
    json.dump(merged, fh, indent=2, ensure_ascii=False)

print(f"ground_truth.json now has {len(merged)} cases")
