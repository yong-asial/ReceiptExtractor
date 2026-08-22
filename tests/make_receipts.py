"""Generate synthetic receipt images plus a ground-truth file for scoring."""
import json, os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "receipts")
MONO = "/System/Library/Fonts/Supplemental/Courier New.ttf"
MONO_B = "/System/Library/Fonts/Supplemental/Courier New Bold.ttf"

def render(name, lines, width=520, pad=34, bg=(252, 251, 248)):
    """lines: list of (text, size, bold, align) with align in l/c/r."""
    fonts = {}
    def f(size, bold):
        key = (size, bold)
        if key not in fonts:
            fonts[key] = ImageFont.truetype(MONO_B if bold else MONO, size)
        return fonts[key]

    # measure
    y = pad
    for text, size, bold, _ in lines:
        y += (size + 8) if text is not None else 14
    height = y + pad

    img = Image.new("RGB", (width, height), bg)
    d = ImageDraw.Draw(img)
    y = pad
    for text, size, bold, align in lines:
        if text is None:
            d.line([(pad, y + 6), (width - pad, y + 6)], fill=(150, 150, 150), width=1)
            y += 14
            continue
        font = f(size, bold)
        w = d.textlength(text, font=font)
        if align == "c":
            x = (width - w) / 2
        elif align == "r":
            x = width - pad - w
        else:
            x = pad
        d.text((x, y), text, font=font, fill=(24, 24, 24))
        y += size + 8

    path = os.path.join(OUT, name)
    img.save(path, quality=95)
    return path


def row(label, value, size=15):
    """Label left, value right, on one line using space padding."""
    total = 34
    gap = max(1, total - len(label) - len(value))
    return (label + " " * gap + value, size, False, "l")


cases = []

# --- 1. Clean US coffee shop receipt ---------------------------------------
render("receipt_us_cafe.jpg", [
    ("BLUE HERON COFFEE", 22, True, "c"),
    ("412 Market Street", 13, False, "c"),
    ("Portland, OR 97204", 13, False, "c"),
    (None, 0, False, "l"),
    ("Receipt #: INV-2024-8871", 14, False, "l"),
    ("Date: 03/14/2024", 14, False, "l"),
    ("Server: Dana", 14, False, "l"),
    (None, 0, False, "l"),
    row("2x Latte", "$9.00"),
    row("1x Blueberry Scone", "$4.25"),
    row("1x Cold Brew 16oz", "$5.50"),
    (None, 0, False, "l"),
    row("SUBTOTAL", "$18.75"),
    row("TAX (8.0%)", "$1.50"),
    row("TOTAL", "$20.25", 17),
    (None, 0, False, "l"),
    ("Paid by VISA ****4417", 14, False, "l"),
    ("Thank you!", 14, False, "c"),
])
cases.append({
    "file": "receipt_us_cafe.jpg",
    "truth": {"Vendor Name": "BLUE HERON COFFEE", "Date": "2024-03-14",
              "Invoice Number": "INV-2024-8871", "Subtotal": "18.75",
              "Tax": "1.50", "Total Amount": "20.25", "Currency": "USD",
              "Payment Method": "VISA"},
})

# --- 2. Japanese receipt, JPY (no decimals), Japanese-era-free date ---------
render("receipt_jp_store.jpg", [
    ("SAKURA MART", 22, True, "c"),
    ("Shibuya-ku, Tokyo", 13, False, "c"),
    ("TEL 03-1234-5678", 13, False, "c"),
    (None, 0, False, "l"),
    ("2024/11/05  19:42", 14, False, "l"),
    ("No. 000517", 14, False, "l"),
    (None, 0, False, "l"),
    row("Onigiri x2", "Y 320"),
    row("Green Tea 500ml", "Y 180"),
    row("Bento Set", "Y 680"),
    (None, 0, False, "l"),
    row("Subtotal", "Y 1,180"),
    row("Tax 10%", "Y 118"),
    row("TOTAL", "Y 1,298", 17),
    (None, 0, False, "l"),
    row("CASH", "Y 1,500"),
    row("CHANGE", "Y 202"),
])
cases.append({
    "file": "receipt_jp_store.jpg",
    "truth": {"Vendor Name": "SAKURA MART", "Date": "2024-11-05",
              "Invoice Number": "000517", "Subtotal": "1180",
              "Tax": "118", "Total Amount": "1298", "Currency": "JPY",
              "Payment Method": "CASH"},
})

# --- 3. European invoice: EUR, comma decimals, DD.MM.YYYY -------------------
render("invoice_eu_supplier.jpg", [
    ("NORDLICHT GmbH", 21, True, "l"),
    ("Hafenstrasse 22, 20359 Hamburg", 13, False, "l"),
    ("VAT DE812349901", 13, False, "l"),
    (None, 0, False, "l"),
    ("INVOICE", 19, True, "c"),
    (None, 0, False, "l"),
    ("Invoice No.  2024-DE-4472", 14, False, "l"),
    ("Invoice Date 22.07.2024", 14, False, "l"),
    ("Due Date     21.08.2024", 14, False, "l"),
    (None, 0, False, "l"),
    row("Design consulting 12h", "1.440,00"),
    row("Print production", "285,50"),
    (None, 0, False, "l"),
    row("Net total", "EUR 1.725,50"),
    row("VAT 19%", "EUR 327,85"),
    row("Amount due", "EUR 2.053,35", 17),
    (None, 0, False, "l"),
    ("Payment: Bank transfer (SEPA)", 14, False, "l"),
], width=560)
cases.append({
    "file": "invoice_eu_supplier.jpg",
    "truth": {"Vendor Name": "NORDLICHT GmbH", "Date": "2024-07-22",
              "Invoice Number": "2024-DE-4472", "Subtotal": "1725.50",
              "Tax": "327.85", "Total Amount": "2053.35", "Currency": "EUR",
              "Payment Method": "Bank transfer"},
})

# --- 4. Same receipt as a bad phone photo: rotated, dim, blurry, noisy ------
src = render("_tmp_gas.jpg", [
    ("HIGHWAY 9 FUEL STOP", 20, True, "c"),
    ("1180 Old Mill Rd", 13, False, "c"),
    (None, 0, False, "l"),
    ("TRANS 774213", 14, False, "l"),
    ("06-30-2024  07:15 AM", 14, False, "l"),
    ("PUMP 4  UNLEADED", 14, False, "l"),
    (None, 0, False, "l"),
    row("11.402 GAL @ 3.859", "$44.00"),
    (None, 0, False, "l"),
    row("SUBTOTAL", "$44.00"),
    row("TAX", "$0.00"),
    row("TOTAL", "$44.00", 17),
    (None, 0, False, "l"),
    ("DEBIT CARD  ****9082", 14, False, "l"),
])
from PIL import ImageEnhance, ImageFilter
img = Image.open(src)
img = img.rotate(-6, expand=True, fillcolor=(70, 70, 72), resample=Image.BICUBIC)
img = ImageEnhance.Brightness(img).enhance(0.72)
img = img.filter(ImageFilter.GaussianBlur(0.6))
# sprinkle sensor noise
import struct
px = img.load()
seed = 12345
for y in range(0, img.height, 3):
    for x in range(0, img.width, 3):
        seed = (1103515245 * seed + 12345) % (2**31)
        n = (seed % 31) - 15
        r, g, b = px[x, y]
        px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)))
img.save(os.path.join(OUT, "receipt_photo_gas.jpg"), quality=72)
os.remove(src)
cases.append({
    "file": "receipt_photo_gas.jpg",
    "truth": {"Vendor Name": "HIGHWAY 9 FUEL STOP", "Date": "2024-06-30",
              "Invoice Number": "774213", "Subtotal": "44.00",
              "Tax": "0.00", "Total Amount": "44.00", "Currency": "USD",
              "Payment Method": "DEBIT CARD"},
})

with open(os.path.join(OUT, "ground_truth.json"), "w") as fh:
    json.dump(cases, fh, indent=2)

print(f"Wrote {len(cases)} receipts to {OUT}")
for c in cases:
    p = os.path.join(OUT, c["file"])
    print(f"  {c['file']}  {Image.open(p).size}")
