"""
Private Receipt Extractor
=========================

Reads receipt and invoice images with a vision model running on this machine
and hands back a spreadsheet. Nothing is uploaded anywhere.

The file is written to be read top to bottom. It follows one receipt through
the whole journey:

    Settings      what to extract, and the limits
    Part 1        check the files the user dropped in
    Part 2        prepare an image so the model can read it
    Part 3        ask the model, and get JSON back
    Part 4        tidy the answer up and flag anything doubtful
    Part 5        pick a model
    Part 6        the web page itself

Nothing here talks to the internet. `ollama` is a local program; every call to
it goes to another process on this same computer.
"""

import io
import json
import re
import warnings
from datetime import date

import ollama
import pandas as pd
import streamlit as st
from PIL import Image, ImageOps

# --- Settings ----------------------------------------------------------------
# This is the part you are most likely to want to change.

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

# What we say to the model. It is just English — edit it to suit your business.
# If you change FIELDS, read Part 4 too: it knows which columns are amounts and
# which one is a date.
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

# What we write in a column when the value simply isn't on the document.
NOT_FOUND = "Not Found"

# Long side, in pixels, that images are shrunk to before going to the model.
# Big photos are slow and no more accurate; ~1400px keeps small print readable.
MAX_EDGE = 1400

# Upload limits. Streamlit reads the whole file into memory before this script
# sees it, so the per-image cap is also set in .streamlit/config.toml; this one
# is the backstop for when the app is started from somewhere else.
MAX_FILE_BYTES = 10 * 1024 * 1024      # 10 MB for a single image
MAX_TOTAL_BYTES = 20 * 1024 * 1024     # 20 MB for everything in one batch

# Refuse absurd pixel counts. A heavily compressed 200-megapixel photo can sit
# well under 10 MB on disk and still need gigabytes of RAM to decode.
MAX_PIXELS = 80_000_000

# Extensions the file picker offers. This is only a first filter: an extension
# is a claim, not a fact, so the bytes are checked too (see image_problem).
IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff"]


# --- Part 1: check the uploaded files ----------------------------------------

def human_size(num_bytes: int) -> str:
    """Format a byte count the way a person would say it: '12.4 MB', '840 KB'."""
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / 1024:.0f} KB"


def image_problem(raw: bytes) -> str:
    """Say why these bytes are not a usable image, or return "" if they are.

    The extension only tells us what the file is called. A renamed PDF, a
    half-finished download and a real photo can all arrive as "receipt.jpg",
    so the header is decoded before anything is sent to the model.
    """
    try:
        with warnings.catch_warnings():
            # Pillow warns about huge images on the terminal. The pixel check
            # just below says the same thing in the browser, where the person
            # using the app will actually see it.
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(raw))
            width, height = img.size
            img.verify()      # verify() consumes the object; reopen to use it
    except Exception:
        return "is not an image we can read — it may be renamed, or corrupt."

    if width * height > MAX_PIXELS:
        return (f"is {width}×{height} pixels, which is too large to process. "
                "Save it at a smaller size and try again.")
    return ""


def check_uploads(files):
    """Split an upload set into images we will read and complaints to show.

    Returns two lists:
      accepted — (file name, image bytes) pairs that passed every check
      problems — ready-to-display messages, one per rejected file

    A batch over the total limit is rejected whole rather than trimmed. A CSV
    that quietly dropped three receipts looks exactly like a complete one.
    """
    accepted, problems = [], []

    for file in files or []:
        raw = file.getvalue()

        if not raw:
            problems.append(f"**{file.name}** is empty.")
            continue

        if len(raw) > MAX_FILE_BYTES:
            problems.append(
                f"**{file.name}** is {human_size(len(raw))}, over the "
                f"{human_size(MAX_FILE_BYTES)} limit for one image. "
                "Photograph it at a lower resolution, or shrink it first."
            )
            continue

        problem = image_problem(raw)
        if problem:
            problems.append(f"**{file.name}** {problem}")
        else:
            accepted.append((file.name, raw))

    total = sum(len(raw) for _, raw in accepted)
    if total > MAX_TOTAL_BYTES:
        problems.append(
            f"These {len(accepted)} images come to {human_size(total)} together, "
            f"over the {human_size(MAX_TOTAL_BYTES)} limit for one batch. "
            "Remove a few and run the rest afterwards."
        )
        accepted = []

    return accepted, problems


# --- Part 2: prepare an image ------------------------------------------------

def prepare_image(raw: bytes) -> bytes:
    """Shrink, straighten and re-encode a photo so the model can read it."""
    img = Image.open(io.BytesIO(raw))

    # Phone photos record "this was taken sideways" in EXIF data rather than
    # rotating the pixels. The model only sees pixels, so rotate them here.
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass          # no EXIF, or an unreadable one: the original is fine

    # JPEG has no transparency. A see-through PNG converted straight to JPEG
    # comes out on a black background, which hides the print, so paste it onto
    # white first — the colour paper would have been.
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        white = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(white, img)
    img = img.convert("RGB")

    # Shrink the long edge to MAX_EDGE, keeping the proportions.
    longest = max(img.size)
    if longest > MAX_EDGE:
        scale = MAX_EDGE / longest
        width = max(1, round(img.width * scale))
        height = max(1, round(img.height * scale))
        img = img.resize((width, height), Image.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


# --- Part 3: ask the model ---------------------------------------------------

def _load_json(text: str):
    """json.loads, but return None instead of raising on malformed text."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def parse_json(text: str) -> dict:
    """Pull the JSON object out of the model's reply, tolerating stray prose."""
    text = text.strip()

    # Strip ```json ... ``` fences, in case the model added them anyway.
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)

    data = _load_json(text)
    if data is None:
        # Fall back to the outermost { ... } and ignore any chatter around it.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            data = _load_json(text[start:end + 1])

    # Some models wrap the single answer in a list. Unwrap it.
    if isinstance(data, list) and len(data) == 1:
        data = data[0]

    if not isinstance(data, dict):
        raise ValueError(
            f"the model replied with something that is not a receipt: {text[:200]}")
    return data


def extract(image_bytes: bytes, model: str) -> dict:
    """Run one image through the local model and return a normalised row."""
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": PROMPT, "images": [image_bytes]}],
        # temperature 0 keeps repeated runs on the same receipt consistent.
        options={"temperature": 0},
    )
    return normalise(parse_json(response["message"]["content"]))


def friendly_error(exc: Exception) -> str:
    """Rewrite an exception as something a non-programmer can act on."""
    text = str(exc).strip()
    lowered = text.lower()

    if any(word in lowered for word in
           ("connect", "refused", "timed out", "timeout", "connection")):
        return ("the local AI engine stopped answering. Check that the Ollama "
                "app is still running, then try again.")
    if "memory" in lowered:
        return ("this computer ran out of memory for that model. Close other "
                "apps, or pick a smaller model such as qwen2.5vl:3b.")
    if "status code: 404" in lowered or "not found, try pulling" in lowered:
        return ("that model is no longer installed. Reload this page to pick "
                "another one.")
    return text or "an unexpected error"


# --- Part 4: tidy the answer up ----------------------------------------------

# Every way a model has of saying "this wasn't on the document".
BLANKS = {"", "-", "--", "n/a", "na", "none", "null", "nil",
          "not found", "not available", "unknown"}


def as_text(value) -> str:
    """Trim a value to a string, turning every kind of blank into "Not Found"."""
    if value is None:
        return NOT_FOUND
    text = str(value).strip()
    return NOT_FOUND if text.lower() in BLANKS else text


def clean_amount(value) -> str:
    """Normalise '$1,234.56' or '1.725,50 EUR' style strings to '1234.56'."""
    text = as_text(value)
    if text == NOT_FOUND:
        return NOT_FOUND

    # Drop currency symbols, spaces and words; keep digits, separators, minus.
    text = re.sub(r"[^\d.,\-]", "", text)

    if "," in text and "." in text:
        # Both separators present: the rightmost one is the decimal point.
        # 1,234.56 is American; 1.234,56 is European.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        # A lone comma is a decimal comma only when it looks like one: 1,50.
        # In 1,298 it is a thousands separator.
        decimal_comma = re.fullmatch(r"-?\d+,\d{1,2}", text)
        text = text.replace(",", "." if decimal_comma else "")

    # 1.234.567 can only be thousands separators — a number has one decimal point.
    if text.count(".") > 1:
        text = text.replace(".", "")

    # Whatever is left has to look like a number, or it never was an amount.
    return text if re.fullmatch(r"-?\d+(\.\d+)?", text) else NOT_FOUND


def is_ambiguous_amount(value: str) -> bool:
    """True for values like '1.234', where the dot could be either separator.

    '1.234' is 1234 to a German reader and 1.234 to an American one. Guessing
    wrong misstates the figure by 1000x, so we surface it instead of picking.
    """
    return bool(re.fullmatch(r"-?\d{1,3}\.\d{3}", str(value).strip()))


MONTH_NAMES = ["jan", "feb", "mar", "apr", "may", "jun",
               "jul", "aug", "sep", "oct", "nov", "dec"]


def month_number(name: str):
    """'March' or 'Mar' -> 3. Returns None for anything else."""
    prefix = name[:3].lower()
    return MONTH_NAMES.index(prefix) + 1 if prefix in MONTH_NAMES else None


def as_iso_date(year, month, day) -> str:
    """Format year/month/day as YYYY-MM-DD, or "" if that is not a real date."""
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except (ValueError, TypeError):
        return ""       # e.g. the 31st of February, or a bad month number


def clean_date(value) -> str:
    """Coerce common receipt date formats to YYYY-MM-DD.

    Only unambiguous cases are converted. 06/07/2024 could be June 7th or
    July 6th, so it is left exactly as printed and flagged for review rather
    than silently filed under the wrong month.
    """
    text = as_text(value)
    if text == NOT_FOUND:
        return NOT_FOUND

    # Already the format we want.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text

    # Japanese style: 2024年11月5日. A trailing weekday such as (火) is ignored.
    match = re.match(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if match:
        return as_iso_date(*match.groups()) or text

    # Year first, any separator: 2024/11/05, 2024.11.05
    match = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if match:
        return as_iso_date(*match.groups()) or text

    # "14 Mar 2024"
    match = re.fullmatch(r"(\d{1,2})[\s-]+([A-Za-z]{3,})\.?[\s-]+(\d{4})", text)
    if match and month_number(match.group(2)):
        day, month, year = match.groups()
        return as_iso_date(year, month_number(month), day) or text

    # "Mar 14, 2024"
    match = re.fullmatch(r"([A-Za-z]{3,})\.?[\s-]+(\d{1,2}),?[\s-]+(\d{4})", text)
    if match and month_number(match.group(1)):
        month, day, year = match.groups()
        return as_iso_date(year, month_number(month), day) or text

    # Two numbers then a year. Safe only when one of them is too big to be a
    # month, which settles the order: 30/06/2024 has to be day first.
    match = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", text)
    if match:
        first, second, year = (int(group) for group in match.groups())
        if first > 12 and second <= 12:                  # DD-MM-YYYY
            return as_iso_date(year, second, first) or text
        if second > 12 and first <= 12:                  # MM-DD-YYYY
            return as_iso_date(year, first, second) or text

    return text   # ambiguous or unrecognised: keep verbatim, flag_issues() warns


AMOUNT_FIELDS = ("Subtotal", "Tax", "Total Amount")


def normalise(row: dict) -> dict:
    """Force the model's dict into our exact schema with tidy values."""
    tidy = {}
    for field in FIELDS:
        value = row.get(field, NOT_FOUND)
        if field in AMOUNT_FIELDS:
            tidy[field] = clean_amount(value)
        elif field == "Date":
            tidy[field] = clean_date(value)
        else:
            tidy[field] = as_text(value)
    return tidy


def flag_issues(row: dict) -> str:
    """Cheap sanity checks so a human knows which rows to eyeball.

    Returns a short note for the "Needs Review" column, or "" if nothing here
    looks suspect. This is the safety net: the model is usually right, and
    "usually" is not good enough for a set of books.
    """
    problems = []

    if row["Total Amount"] == NOT_FOUND:
        problems.append("no total")

    ambiguous = [f for f in AMOUNT_FIELDS if is_ambiguous_amount(row[f])]
    if ambiguous:
        problems.append(f"check separator in {', '.join(ambiguous)}")

    if row["Date"] == NOT_FOUND:
        problems.append("no date")
    elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["Date"]):
        problems.append("odd date format")

    # Subtotal + tax should equal the total. If it doesn't, the model misread
    # one of the three. Rows where any of them is missing are skipped: float()
    # raises on "Not Found" and there is nothing to compare anyway.
    try:
        subtotal = float(row["Subtotal"])
        tax = float(row["Tax"])
        total = float(row["Total Amount"])
        if abs((subtotal + tax) - total) > 0.02:
            problems.append("subtotal + tax != total")
    except (ValueError, TypeError):
        pass

    return ", ".join(problems)


# --- Part 5: pick a model ----------------------------------------------------

# Families measured on receipts, best first. Everything else vision-capable is
# still offered, just below these.
PREFERRED = ("qwen2.5vl", "qwen2-vl", "minicpm-v", "llava", "gemma3", "granite")

# Ollama dropped support for Llama 3.2 Vision's architecture. The model still
# downloads and still advertises a "vision" capability, then fails to load with
# "unknown model architecture: 'mllama'". Hide it rather than offer a choice
# that can only fail on the first receipt.
BROKEN_ARCHITECTURES = {"mllama"}


def field_of(obj, name, default=None):
    """Read one field from an Ollama reply, which may be an object or a dict."""
    value = getattr(obj, name, None)
    if value is None and isinstance(obj, dict):
        value = obj.get(name)
    return default if value is None else value


def list_models():
    """Return (vision-capable model names best-first, how many were hidden).

    Ollama reports what each model can actually do, so text-only models
    (llama3, mistral) and embedding models (nomic-embed-text) are excluded by
    asking rather than by guessing from their names. None of them can read an
    image, so offering them only invites a confusing failure.
    """
    try:
        installed = list(field_of(ollama.list(), "models", []))
    except Exception:
        return (), 0        # Ollama isn't running; the page says so

    usable, hidden = [], 0
    for entry in installed:
        name = field_of(entry, "model") or field_of(entry, "name")
        if not name:
            continue
        try:
            info = ollama.show(name)
            capabilities = [str(c).lower() for c in field_of(info, "capabilities", [])]
            architecture = str(field_of(field_of(info, "modelinfo", {}),
                                        "general.architecture", "")).lower()
            family = str(field_of(field_of(info, "details", {}), "family", "")).lower()
        except Exception:
            hidden += 1     # can't confirm it works, so don't offer it
            continue

        broken = architecture in BROKEN_ARCHITECTURES or family in BROKEN_ARCHITECTURES
        if "vision" not in capabilities or broken:
            hidden += 1
            continue
        usable.append(name)

    def rank(name: str):
        """Sort key: known-good families first, then bigger sizes, then A-Z."""
        low = name.lower()
        for position, family in enumerate(PREFERRED):
            if family in low:
                # Within a family, bigger tends to read small print better.
                bigger_first = 0 if (":7b" in low or ":8b" in low) else 1
                return (0, position, bigger_first, low)
        return (1, 0, 0, low)

    return tuple(sorted(usable, key=rank)), hidden


# --- Part 6: the web page ----------------------------------------------------
# Streamlit re-runs this whole file from the top on every click. Anything that
# has to survive a click therefore lives in st.session_state, not in a variable.

# "wide" so the ten-column results table fits without horizontal scrolling.
st.set_page_config(page_title="Private Receipt Extractor", page_icon="🧾",
                   layout="wide")
st.title("🧾 Private Receipt Extractor")
st.caption(
    "Drop in your receipts and get a spreadsheet back. "
    "Runs entirely on this computer — nothing is uploaded."
)

available, hidden = list_models()
if not available:
    st.error(
        "No model here can read images.\n\n"
        "Run `ollama pull qwen2.5vl:7b` in a terminal, then reload this page. "
        "If that is already done, check the Ollama app is running."
    )
    st.stop()

model = st.selectbox("AI model", available,
                     help="Only models that can read images are listed.")
if hidden:
    st.caption(
        f"{hidden} other installed model{'s' if hidden > 1 else ''} "
        f"hidden — text-only or embedding models cannot read receipts."
    )

uploaded_files = st.file_uploader(
    "Receipts",
    type=IMAGE_EXTENSIONS,
    accept_multiple_files=True,
    help=f"Photos and scans only — up to {human_size(MAX_FILE_BYTES)} per image "
         f"and {human_size(MAX_TOTAL_BYTES)} in one go.",
)

accepted, problems = check_uploads(uploaded_files)

for message in problems:
    st.error(message)

if accepted:
    total = sum(len(raw) for _, raw in accepted)
    st.caption(
        f"{len(accepted)} image{'s' if len(accepted) > 1 else ''} ready — "
        f"{human_size(total)} of {human_size(MAX_TOTAL_BYTES)}."
    )


def upload_signature(files):
    """Identify the current upload set, so stale results can be dropped."""
    if not files:
        return ()
    # file_id when Streamlit gives us one, name+size otherwise — as a string
    # either way, so a mixed set still sorts.
    return tuple(sorted(
        str(getattr(f, "file_id", None) or f"{f.name}:{f.size}") for f in files))


# Swap the files and the old table stops applying, so throw it away.
signature = upload_signature(uploaded_files)
if st.session_state.get("signature") != signature:
    st.session_state["signature"] = signature
    st.session_state.pop("results", None)
    st.session_state.pop("failures", None)

if accepted and st.button("Extract data", type="primary"):
    rows, failures = [], []
    progress = st.progress(0.0, text="Starting…")

    for position, (name, raw) in enumerate(accepted):
        progress.progress(position / len(accepted), text=f"Reading {name}…")
        try:
            row = extract(prepare_image(raw), model)
            row["Needs Review"] = flag_issues(row)
            row["File Name"] = name
            rows.append(row)
        except Exception as exc:
            # One unreadable receipt must not stop the other nineteen.
            failures.append((name, friendly_error(exc)))

    progress.empty()
    st.session_state["results"] = rows
    st.session_state["failures"] = failures

# --- Results, redrawn on every rerun -----------------------------------------
# These sit outside the button block on purpose. Clicking Download re-runs the
# script, and results read from a local variable would vanish at that moment.

for name, error in st.session_state.get("failures", []):
    st.error(f"Couldn't read **{name}** — {error}")

rows = st.session_state.get("results")
if rows:
    table = pd.DataFrame(rows)[FIELDS + ["Needs Review", "File Name"]]

    needs_review = int((table["Needs Review"] != "").sum())
    if needs_review:
        st.warning(
            f"{needs_review} of {len(table)} receipts have something worth "
            "double-checking — see the **Needs Review** column."
        )
    else:
        st.success(f"Read {len(table)} receipts.")

    st.dataframe(table, width="stretch")

    st.download_button(
        "📥 Download as spreadsheet (CSV)",
        # utf-8-sig, not plain utf-8: the marker it adds is what makes Excel
        # open Japanese and other non-Latin text correctly.
        data=table.to_csv(index=False).encode("utf-8-sig"),
        file_name="receipts.csv",
        mime="text/csv",
    )
