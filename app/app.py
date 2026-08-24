"""
Private Receipt Extractor
Reads receipt/invoice images with a local vision model and exports a CSV.
Nothing is uploaded anywhere: the model runs on this machine via Ollama.
"""

import io
import json
import re

import ollama
import pandas as pd
import streamlit as st
from PIL import Image

# --- Configuration -----------------------------------------------------------

# Columns we ask the model for, in the order they should appear in the CSV.
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


# --- Helpers -----------------------------------------------------------------

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
        img = Image.open(io.BytesIO(raw))
        width, height = img.size
        img.verify()          # verify() consumes the object; reopen to use it
    except Exception:
        return "is not an image we can read — it may be renamed, or corrupt."

    if width * height > MAX_PIXELS:
        return (f"is {width}×{height} pixels, which is too large to process. "
                "Save it at a smaller size and try again.")
    return ""


def check_uploads(files) -> tuple:
    """Split an upload set into images we will read and complaints to show.

    Returns (accepted, problems): accepted is a list of (name, image_bytes),
    problems is a list of ready-to-display messages. A batch over the total
    limit is rejected whole rather than trimmed — a CSV that quietly dropped
    three receipts looks exactly like a complete one.
    """
    accepted, problems = [], []

    for file in files or []:
        raw = file.getvalue()

        if not raw:
            problems.append(f"**{file.name}** is empty.")
        elif len(raw) > MAX_FILE_BYTES:
            problems.append(
                f"**{file.name}** is {human_size(len(raw))}, over the "
                f"{human_size(MAX_FILE_BYTES)} limit for one image. "
                "Photograph it at a lower resolution, or shrink it first."
            )
        else:
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


def prepare_image(raw: bytes) -> bytes:
    """Downscale, flatten transparency, honour EXIF rotation, re-encode as JPEG."""
    img = Image.open(io.BytesIO(raw))

    # Phone photos carry rotation in EXIF; models see the raw pixels, so apply it.
    try:
        from PIL import ImageOps

        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    if max(img.size) > MAX_EDGE:
        scale = MAX_EDGE / max(img.size)
        new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        img = img.resize(new_size, Image.LANCZOS)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=90)
    return out.getvalue()


def parse_json(text: str) -> dict:
    """Pull a JSON object out of the model's reply, tolerating stray prose."""
    text = text.strip()

    # Strip ```json ... ``` fences if the model added them anyway.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fall back to the outermost {...} span.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError(f"No JSON object in model reply: {text[:200]}")


def clean_amount(value) -> str:
    """Normalise '$1,234.56' / '1 234,56 EUR' style strings to '1234.56'."""
    if value is None:
        return "Not Found"
    s = str(value).strip()
    if not s or s.lower() in {"not found", "n/a", "none", "null", "-"}:
        return "Not Found"

    # Drop everything that is not a digit, separator, or minus sign.
    s = re.sub(r"[^\d.,\-]", "", s)
    if not s:
        return "Not Found"

    # If both separators appear, the rightmost one is the decimal point.
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # A single comma is a decimal comma only when it looks like one (1,50).
        s = s.replace(",", ".") if re.fullmatch(r"-?\d+,\d{1,2}", s) else s.replace(",", "")

    return s


def is_ambiguous_amount(value: str) -> bool:
    """True for values like '1.234', where the dot could be either separator.

    '1.234' is 1234 to a German reader and 1.234 to an American one. Guessing
    wrong misstates the figure by 1000x, so we surface it instead of picking.
    """
    return bool(re.fullmatch(r"-?\d{1,3}\.\d{3}", str(value).strip()))


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def clean_date(value) -> str:
    """Coerce common receipt date formats to YYYY-MM-DD.

    Only unambiguous cases are converted. 06/07/2024 could be June 7th or
    July 6th, so it is left exactly as printed and flagged for review rather
    than silently filed under the wrong month.
    """
    if value is None:
        return "Not Found"
    s = str(value).strip()
    if not s or s.lower() in {"not found", "n/a", "none", "null", "-"}:
        return "Not Found"

    # Already correct.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s

    # Japanese style: 2024年11月5日 (optionally with a trailing weekday).
    m = re.match(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", s)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"

    # YYYY?MM?DD with any separator.
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"

    # "14 Mar 2024" / "Mar 14, 2024".
    m = re.fullmatch(r"(\d{1,2})[\s-]+([A-Za-z]{3,})\.?[\s-]+(\d{4})", s)
    if m and m.group(2)[:3].lower() in MONTHS:
        return f"{int(m.group(3)):04d}-{MONTHS[m.group(2)[:3].lower()]:02d}-{int(m.group(1)):02d}"
    m = re.fullmatch(r"([A-Za-z]{3,})\.?[\s-]+(\d{1,2}),?[\s-]+(\d{4})", s)
    if m and m.group(1)[:3].lower() in MONTHS:
        return f"{int(m.group(3)):04d}-{MONTHS[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}"

    # Two numbers then a year: only safe when one of them must be the day.
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)
    if m:
        a, b, y = (int(g) for g in m.groups())
        if a > 12 and b <= 12:          # DD-MM-YYYY
            return f"{y:04d}-{b:02d}-{a:02d}"
        if b > 12 and a <= 12:          # MM-DD-YYYY
            return f"{y:04d}-{a:02d}-{b:02d}"

    return s   # ambiguous or unrecognised: keep verbatim, flag_issues() warns


def normalise(row: dict) -> dict:
    """Force the model's dict into our exact schema with tidy values."""
    out = {}
    for field in FIELDS:
        value = row.get(field, "Not Found")
        if field in ("Subtotal", "Tax", "Total Amount"):
            out[field] = clean_amount(value)
        elif field == "Date":
            out[field] = clean_date(value)
        else:
            text = str(value).strip() if value is not None else ""
            out[field] = text if text else "Not Found"
    return out


def flag_issues(row: dict) -> str:
    """Cheap sanity checks so a human knows which rows to eyeball."""
    problems = []

    if row["Total Amount"] == "Not Found":
        problems.append("no total")

    ambiguous = [f for f in ("Subtotal", "Tax", "Total Amount")
                 if is_ambiguous_amount(row[f])]
    if ambiguous:
        problems.append(f"check separator in {', '.join(ambiguous)}")

    if row["Date"] == "Not Found":
        problems.append("no date")
    elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["Date"]):
        problems.append("odd date format")

    # Subtotal + tax should equal the total. If it doesn't, the model misread one.
    try:
        subtotal = float(row["Subtotal"])
        tax = float(row["Tax"])
        total = float(row["Total Amount"])
        if abs((subtotal + tax) - total) > 0.02:
            problems.append("subtotal + tax != total")
    except (ValueError, TypeError):
        pass

    return ", ".join(problems)


def extract(image_bytes: bytes, model: str) -> dict:
    """Run one image through the local model and return a normalised row."""
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": PROMPT, "images": [image_bytes]}],
        # temperature 0 keeps repeated runs on the same receipt consistent.
        options={"temperature": 0},
    )
    return normalise(parse_json(response["message"]["content"]))


# Families measured on receipts, best first. Everything else vision-capable is
# still offered, just below these.
PREFERRED = ("qwen2.5vl", "qwen2-vl", "minicpm-v", "llava", "gemma3", "granite")

# Ollama dropped support for Llama 3.2 Vision's architecture. The model still
# downloads and still advertises a "vision" capability, then fails to load with
# "unknown model architecture: 'mllama'". Hide it rather than offer a choice
# that can only fail on the first receipt.
BROKEN_ARCHITECTURES = {"mllama"}


def _field(obj, name, default=None):
    """Read a field from an Ollama response, which may be an object or a dict."""
    if obj is None:
        return default
    value = getattr(obj, name, None)
    if value is None and hasattr(obj, "get"):
        try:
            value = obj.get(name)
        except Exception:
            value = None
    return default if value is None else value


def list_models() -> tuple:
    """Return (vision-capable models best-first, number hidden).

    Ollama reports what each model can actually do, so text-only models
    (llama3, mistral) and embedding models (nomic-embed-text) are excluded by
    asking rather than by guessing from their names. None of them can read an
    image, so offering them only invites a confusing failure.
    """
    try:
        names = [m.get("model") or m.get("name") for m in ollama.list()["models"]]
    except Exception:
        return (), 0

    usable, hidden = [], 0
    for name in [n for n in names if n]:
        try:
            info = ollama.show(name)
            caps = [str(c).lower() for c in _field(info, "capabilities", [])]
            arch = str(_field(_field(info, "modelinfo", {}), "general.architecture", "")).lower()
            family = str(_field(_field(info, "details", {}), "family", "")).lower()
        except Exception:
            hidden += 1          # can't confirm it works, so don't offer it
            continue

        if "vision" not in caps or arch in BROKEN_ARCHITECTURES or family in BROKEN_ARCHITECTURES:
            hidden += 1
            continue
        usable.append(name)

    def rank(name: str) -> tuple:
        low = name.lower()
        for i, fam in enumerate(PREFERRED):
            if fam in low:
                # Within a family, bigger tends to read small print better.
                return (0, i, 0 if ":7b" in low or ":8b" in low else 1, low)
        return (1, 0, 0, low)

    return tuple(sorted(usable, key=rank)), hidden


# --- UI ----------------------------------------------------------------------

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


def upload_signature(files) -> tuple:
    """Identify the current upload set, so stale results can be dropped."""
    if not files:
        return ()
    # file_id when Streamlit gives us one, name+size otherwise — as a string
    # either way, so a mixed set still sorts.
    return tuple(sorted(
        str(getattr(f, "file_id", None) or f"{f.name}:{f.size}") for f in files))


# Streamlit re-runs this whole script on every interaction — including the
# download click. Results therefore live in session_state and are drawn below,
# outside the button block; keeping them in local variables would make the
# table vanish the moment anything else on the page was touched.
signature = upload_signature(uploaded_files)
if st.session_state.get("signature") != signature:
    st.session_state["signature"] = signature
    st.session_state.pop("results", None)
    st.session_state.pop("failures", None)

if accepted and st.button("Extract data", type="primary"):
    rows, failures = [], []
    progress = st.progress(0.0, text="Starting…")

    for i, (name, raw) in enumerate(accepted):
        progress.progress(i / len(accepted), text=f"Reading {name}…")
        try:
            row = extract(prepare_image(raw), model)
            row["Needs Review"] = flag_issues(row)
            row["File Name"] = name
            rows.append(row)
        except Exception as exc:
            failures.append((name, str(exc)))

    progress.empty()
    st.session_state["results"] = rows
    st.session_state["failures"] = failures

# --- Results, redrawn on every rerun ----------------------------------------

for name, error in st.session_state.get("failures", []):
    st.error(f"Couldn't read **{name}** — {error}")

rows = st.session_state.get("results")
if rows:
    column_order = FIELDS + ["Needs Review", "File Name"]
    df = pd.DataFrame(rows)[column_order]

    needs_review = int((df["Needs Review"] != "").sum())
    if needs_review:
        st.warning(
            f"{needs_review} of {len(df)} receipts have something worth "
            "double-checking — see the **Needs Review** column."
        )
    else:
        st.success(f"Read {len(df)} receipts.")

    st.dataframe(df, use_container_width=True)

    st.download_button(
        "📥 Download as spreadsheet (CSV)",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name="receipts.csv",
        mime="text/csv",
    )
