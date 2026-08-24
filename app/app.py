"""
Private Receipt Extractor — the web page.

Drop in receipt images, press a button, download a spreadsheet. The model runs
on this machine via Ollama, so nothing is uploaded anywhere.

This file is only the page: what you see, and in what order. The work is done
by three neighbours, and each one explains itself at the top:

    settings.py   what to pull off a receipt, and the limits. Start here.
    uploads.py    checking the dropped-in files, and preparing an image
    reader.py     asking the local model, and reading its reply
    tidy.py       turning the reply into figures you could put in a ledger

Run it with:  streamlit run app/app.py
"""

import pandas as pd
import streamlit as st

from settings import (FIELDS, IMAGE_EXTENSIONS, MAX_FILE_BYTES, MAX_TOTAL_BYTES)
from reader import extract, friendly_error, list_models
from tidy import flag_issues
from uploads import check_uploads, human_size, prepare_image, upload_signature

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

# --- Pick a model ------------------------------------------------------------

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

# --- Choose the receipts -----------------------------------------------------

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

# Swap the files and the old table stops applying, so throw it away.
signature = upload_signature(uploaded_files)
if st.session_state.get("signature") != signature:
    st.session_state["signature"] = signature
    st.session_state.pop("results", None)
    st.session_state.pop("failures", None)

# --- Read them ---------------------------------------------------------------

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

# --- Show the results, redrawn on every rerun --------------------------------
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
