"""
What the Receipt Extractor pulls out, and the limits it works within.

This is the file to open first. Almost everything a business would want to
change lives here, and you can change it without touching any other file —
with one exception, noted on AMOUNT_FIELDS below.
"""

import json

# --- What to pull off each receipt -------------------------------------------

# The spreadsheet columns, in the order they should appear.
FIELDS = [
    "Vendor Name",
    "Date",
    "Invoice Number",
    "Subtotal",
    "Tax",
    "Total Amount",
    "Currency",
    "Payment Method",
]

# Which of the FIELDS above hold money, and which one holds a date. These are
# cleaned up differently from ordinary text, so if you add or rename a field,
# check that it is listed here when it should be. Everything else in FIELDS is
# copied across as plain text.
AMOUNT_FIELDS = ("Subtotal", "Tax", "Total Amount")
DATE_FIELD = "Date"

# What we write in a column when the value simply isn't on the document.
NOT_FOUND = "Not Found"

# What we say to the model. It is just English — edit it to suit your business:
# add a purchase order number, drop the payment method, ask for line items, or
# write the rules in your own language. Keep the JSON-only instruction, though;
# the rest of the app expects a JSON object back.
PROMPT = f"""You are a bookkeeping assistant reading a receipt or invoice.

Return ONLY a JSON object with exactly these keys:
{json.dumps(FIELDS, indent=2)}

Rules:
- "Date" is the date the receipt or invoice was ISSUED, not a due date or a
  service period. Return it as YYYY-MM-DD, converting from whatever format the
  document uses (including Japanese 2024年11月5日 style).
- Copy "Vendor Name" and "Payment Method" exactly as printed, in the document's
  own language and script. Do not translate or romanise them.
- Amounts must be plain numbers with no currency symbols and no thousands
  separators, e.g. 1234.56
- "Currency" is the 3-letter code, e.g. USD, JPY, EUR.
- Use the string "Not Found" for anything you cannot read on the receipt.
- Never guess or invent a value. Never do arithmetic to fill a blank.
- Output no markdown, no code fences, no commentary. JSON only.
"""


# --- Limits ------------------------------------------------------------------

# Long side, in pixels, that images are shrunk to before going to the model.
# Big photos are slow and no more accurate; ~1400px keeps small print readable.
MAX_EDGE = 1400

# Upload limits. Streamlit reads the whole file into memory before this app
# sees it, so the per-image cap is also set in .streamlit/config.toml; this one
# is the backstop for when the app is started from somewhere else.
MAX_FILE_BYTES = 10 * 1024 * 1024      # 10 MB for a single image
MAX_TOTAL_BYTES = 20 * 1024 * 1024     # 20 MB for everything in one batch

# Refuse absurd pixel counts. A heavily compressed 200-megapixel photo can sit
# well under 10 MB on disk and still need gigabytes of RAM to decode.
MAX_PIXELS = 80_000_000

# Extensions the file picker offers. This is only a first filter: an extension
# is a claim, not a fact, so the bytes are checked too (see uploads.py).
IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff"]
