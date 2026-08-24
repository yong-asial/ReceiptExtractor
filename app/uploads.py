"""
Getting the dropped-in files ready for the model.

Two jobs, in the order they happen:

  check_uploads()   decide which files we are willing to read, and say why
                    the rest were turned away
  prepare_image()   shrink, straighten and re-encode one accepted image

Nothing here knows about AI. It is all file and image handling.
"""

import io
import warnings

from PIL import Image, ImageOps

from settings import (MAX_EDGE, MAX_FILE_BYTES, MAX_PIXELS, MAX_TOTAL_BYTES)


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


def upload_signature(files):
    """Identify the current upload set, so stale results can be dropped.

    Swap the files in the picker and the table from the previous run no longer
    describes what is on screen. Comparing this signature is how the page
    notices.
    """
    if not files:
        return ()
    # file_id when Streamlit gives us one, name+size otherwise — as a string
    # either way, so a mixed set still sorts.
    return tuple(sorted(
        str(getattr(f, "file_id", None) or f"{f.name}:{f.size}") for f in files))
