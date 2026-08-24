"""
Turning the model's answer into figures you could put in a ledger.

A vision model reads what is printed, so it hands back whatever the receipt
happens to say: "$1,234.56", "1.725,50 EUR", "2024年11月5日", sometimes just a
dash. This file does two things with that:

  normalise()    force the reply into our exact columns, in tidy form
  flag_issues()  say which rows a human should look at before trusting them

The guiding rule throughout is that a wrong number is worse than a missing
one. Where a value is genuinely ambiguous, nothing is guessed: the original
text is kept and the row is flagged instead.
"""

import re
from datetime import date

from settings import AMOUNT_FIELDS, DATE_FIELD, FIELDS, NOT_FOUND

# Every way a model has of saying "this wasn't on the document".
BLANKS = {"", "-", "--", "n/a", "na", "none", "null", "nil",
          "not found", "not available", "unknown"}


def as_text(value) -> str:
    """Trim a value to a string, turning every kind of blank into "Not Found"."""
    if value is None:
        return NOT_FOUND
    text = str(value).strip()
    return NOT_FOUND if text.lower() in BLANKS else text


# --- Amounts -----------------------------------------------------------------

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


# --- Dates -------------------------------------------------------------------

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


# --- Putting a row together --------------------------------------------------

def normalise(row: dict) -> dict:
    """Force the model's dict into our exact schema with tidy values."""
    tidy = {}
    for field in FIELDS:
        value = row.get(field, NOT_FOUND)
        if field in AMOUNT_FIELDS:
            tidy[field] = clean_amount(value)
        elif field == DATE_FIELD:
            tidy[field] = clean_date(value)
        else:
            tidy[field] = as_text(value)
    return tidy


def flag_issues(row: dict) -> str:
    """Cheap sanity checks so a human knows which rows to eyeball.

    Takes a row that has already been through normalise(), and returns a short
    note for the "Needs Review" column, or "" if nothing here looks suspect.
    This is the safety net: the model is usually right, and "usually" is not
    good enough for a set of books.
    """
    problems = []

    if row["Total Amount"] == NOT_FOUND:
        problems.append("no total")

    ambiguous = [f for f in AMOUNT_FIELDS if is_ambiguous_amount(row[f])]
    if ambiguous:
        problems.append(f"check separator in {', '.join(ambiguous)}")

    if row[DATE_FIELD] == NOT_FOUND:
        problems.append("no date")
    elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row[DATE_FIELD]):
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
