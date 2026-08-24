"""
Talking to the AI model, which is running on this same computer.

`ollama` is a local program, not a website. Every call in this file goes to
another process on this machine — nothing is sent over the internet.

  list_models()  which installed models can actually read an image
  extract()      hand one receipt to the model and get a tidy row back

The rest is damage control: models occasionally wrap their JSON in chatter,
and Ollama occasionally isn't running at all.
"""

import json
import re

import ollama

from settings import PROMPT
from tidy import normalise

# --- Reading the model's reply ------------------------------------------------

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


# --- Which models can read a receipt -----------------------------------------

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
