# Stop Uploading Your Receipts to Random Websites

## A receipt-to-spreadsheet tool that never leaves your laptop

If you run a small business you already know this routine. There's a shoebox of
receipts, a month-end deadline, and two unappealing ways through it: type every
line into a spreadsheet yourself, or find one of those free "invoice converter"
sites and hand your company's financial records to a stranger.

I've done both. The second one bothers me more than it seems to bother most
people. Those sites are free for a reason, and the reason is that your documents
are worth something, whether as training data, as marketing signal, or just as
files sitting on a server you have no control over. A receipt tells you who a
company buys from, what its margins look like, which staff member expensed
lunch, and the last four digits of a card.

There's a third option now, and it's finally good enough to bother with. Vision
models that can read a crumpled thermal receipt will run on an ordinary laptop,
offline, for nothing. No account, no API key, no upload. This post is the build.

I tested it before writing it up: six documents, three currencies, 48 fields,
and it got all 48. Two of those documents were entirely in Japanese and one was
a phone photo I ruined on purpose. So, how to build it, and the places where you
still have to look at the screen yourself.

---

## What you get

A page in your browser with a file picker. Drag in receipt images, press one
button, get a table you can download as a CSV and open in Excel, Numbers or
Google Sheets.

![The app when you first open it](images/app-empty.png)

Behind that page, a vision model on your own machine reads each image and pulls
out vendor, date, invoice number, subtotal, tax, total, currency and payment
method.

Setup takes about 15 minutes. After that it's roughly 5 seconds a receipt.

Worth saying plainly up front: this replaces the typing, not the checking. You
still read the numbers before they go into your books. What you're buying is
maybe 90% of the tedium, not an accountant.

---

## What you need first

- A Mac or Windows laptop from the last four years or so. The model runs
  locally, which is the only real requirement here.
- 8 GB of RAM, though 16 is more comfortable. There's a smaller model below if
  you're on 8.
- About 7 GB of free disk for the download.
- The willingness to paste three commands into a terminal. You don't have to
  understand them and I'll give you the exact text.

---

## Two things to get out of the way

**This was built on a Mac.** All the code, the six test documents and every
accuracy figure below came off a macOS machine. Ollama, Python and Streamlit all
run on Windows perfectly well, so I expect the whole thing works there, but I
haven't rerun the tests to prove it. Where something differs on Windows I've put
in a note:

> **On Windows:** notes like this one.

Take those as the Windows equivalents as far as I know them, not as steps I've
verified end to end. Linux doesn't get a mention anywhere but behaves close
enough to the Mac path.

**Check the licence before you use this for paid work.** Free to download and
free to use in a business are two different things, and it's easy to conflate
them because nothing in the process ever asks you to agree to anything.
`ollama pull` just downloads. Every model in the library comes with its own
terms and they vary a lot. Some are permissive, some are research-only, some are
fine until you cross a revenue or user threshold, some put conditions on what
you're allowed to do with the output.

The part that catches people is that sizes within one family don't necessarily
share a licence. `qwen2.5vl:3b` and `qwen2.5vl:7b` are separate releases, so
check the tag you actually pulled rather than the family name. Locally:

```bash
ollama show qwen2.5vl:7b --license
```

Read that and the model card on the vendor's own site before you point this at a
client's books. If you're handling someone else's financial data under contract,
it's a question for whoever approves your software, not for a blog post.

---

## Step 1: Install Ollama

Ollama runs AI models on your computer. It's a normal app, roughly as exotic as
installing Spotify, and after the initial model download it doesn't talk to the
internet.

Get it from **[ollama.com](https://ollama.com)**, install it like anything else,
and open it once. A small llama shows up in your menu bar on a Mac or the system
tray on Windows, which means the engine is running. No signup, no account, no
card.

> **On Windows:** you get a single `OllamaSetup.exe`, and it installs into your
> own user folder rather than `Program Files`, so it won't ask for an admin
> password. It does add `ollama` to your `PATH`, but a terminal window you
> already had open won't have picked that up. Close it and open a fresh one
> before Step 2, or you'll get `'ollama' is not recognized as an internal or
> external command` and assume something went wrong with the install.



---

## Step 2: Get the model

Open a terminal. On a Mac, `Cmd+Space`, type Terminal, Enter. On Windows, Start
key, type Command Prompt, Enter.

> **On Windows:** PowerShell works just as well as Command Prompt and pastes with
> `Ctrl+V` like a normal application, where the old Command Prompt may want a
> right-click instead. Either is fine for everything in this post. The one thing
> to avoid is WSL. Ollama installed inside WSL is a separate engine from Ollama
> installed on Windows, and you'll download six gigabytes twice before working
> out why the app can't see your model.

Then:

```bash
ollama pull qwen2.5vl:7b
```

That's about 6 GB, so go and make coffee. It's a one-time thing.

> **On Windows:** models go to `C:\Users\<you>\.ollama\models`, so the 7 GB has
> to be free on `C:` specifically. A spacious `D:` drive won't help you. The Mac
> equivalent is `~/.ollama/models`.

Only 8 GB of RAM? Take the small one instead:

```bash
ollama pull qwen2.5vl:3b
```

3.2 GB, and it scored exactly the same as the 7b on every test I ran, Japanese
included. I did not expect that. If you're tight on space or memory, start here
and don't feel like you're settling for less.

---

## Step 3: Three Python libraries

Same terminal:

```bash
pip install streamlit pandas ollama pillow
```

streamlit makes the web page, pandas makes the spreadsheet, ollama talks to the
engine, and pillow tidies up the images before the model sees them.

If `pip` isn't recognised, get Python from [python.org](https://python.org) and
tick "Add Python to PATH" while installing.

> **On Windows:** Python isn't preinstalled, so you'll almost certainly need that
> download, and "Add Python to PATH" on the first installer screen is the
> checkbox everyone skips. Avoid the Microsoft Store version of Python too; its
> sandboxed file permissions produce strange Streamlit failures that are no fun
> to debug. Once it's in, use:
>
> ```
> py -m pip install streamlit pandas ollama pillow
> ```
>
> `py -m pip` rather than plain `pip` makes sure you're installing into the same
> Python that ends up running the app.

On a Mac you may get `error: externally-managed-environment` instead. That's a
Python safety guard, not something you broke. Either use
`pip3 install --user streamlit pandas ollama pillow`, or set up a virtual
environment in the project folder with
`python3 -m venv .venv && source .venv/bin/activate` and install inside that.

---

## Step 4: The app

Make a folder on your Desktop called `ReceiptExtractor`, and inside it a file
called `app.py` with the code below in it.

> **On Windows:** use Notepad, VS Code, anything that saves plain text. Not Word.
> If you're in Notepad, go **Save as**, change *Save as type* to **All Files**,
> and then type `app.py`; otherwise Windows saves it as `app.py.txt` and nothing
> runs. Leave the encoding on UTF-8, because there's Japanese in the code.

You don't need to follow the code to use it. I've commented the parts that
matter, since a few of them are the difference between a demo and something
you'd let near real books.

````python
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


# --- Helpers -----------------------------------------------------------------

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
    type=["jpg", "jpeg", "png", "webp", "bmp", "tiff"],
    accept_multiple_files=True,
)

def upload_signature(files) -> tuple:
    """Identify the current upload set, so stale results can be dropped."""
    if not files:
        return ()
    return tuple(sorted(getattr(f, "file_id", None) or (f.name, f.size)
                        for f in files))


# Streamlit re-runs this whole script on every interaction — including the
# download click. Results therefore live in session_state and are drawn below,
# outside the button block; keeping them in local variables would make the
# table vanish the moment anything else on the page was touched.
signature = upload_signature(uploaded_files)
if st.session_state.get("signature") != signature:
    st.session_state["signature"] = signature
    st.session_state.pop("results", None)
    st.session_state.pop("failures", None)

if uploaded_files and st.button("Extract data", type="primary"):
    rows, failures = [], []
    progress = st.progress(0.0, text="Starting…")

    for i, file in enumerate(uploaded_files):
        progress.progress(i / len(uploaded_files), text=f"Reading {file.name}…")
        try:
            row = extract(prepare_image(file.getvalue()), model)
            row["Needs Review"] = flag_issues(row)
            row["File Name"] = file.name
            rows.append(row)
        except Exception as exc:
            failures.append((file.name, str(exc)))

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
````

---

## Step 5: Run it

Back in the terminal:

```bash
cd Desktop/ReceiptExtractor
streamlit run app.py
```

> **On Windows:** backslashes, and it's safest to spell the path out:
>
> ```
> cd %USERPROFILE%\Desktop\ReceiptExtractor
> py -m streamlit run app.py
> ```
>
> In PowerShell, use `cd $HOME\Desktop\ReceiptExtractor` instead. Two gotchas
> here. If bare `streamlit` isn't recognised, `py -m streamlit` always works;
> it's the same program found a more reliable way. And if OneDrive is syncing
> your Desktop, the real path is `%USERPROFILE%\OneDrive\Desktop\...`, so run
> `dir %USERPROFILE%` to see which of the two you've got. You may also get a
> firewall prompt the first time, which you can safely cancel, since nothing
> here needs to accept connections from anywhere.

The browser opens by itself. Drag in some receipts, click **Extract data**, and
watch the bar. The first one takes 10-20 seconds while the model loads into
memory, then it settles down to about 5 seconds each.

`Ctrl+C` in the terminal stops it. Tomorrow, same two commands. (That's `Ctrl`
and not `Cmd`, even on a Mac.)
