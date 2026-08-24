"""Regression test: the results table must survive a download click.

Streamlit re-runs the script on every interaction. If results live in local
variables inside the `if st.button(...)` block, clicking download re-runs the
script, the button returns False, and the whole table disappears.
"""
import os, sys
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
REC = os.path.join(HERE, "receipts")
# Override with APP_URL=http://127.0.0.1:8502 to test a second instance.
URL = os.environ.get("APP_URL", "http://127.0.0.1:8501")
FILES = ["receipt_us_cafe.jpg", "receipt_ja_konbini.jpg"]

def rows_visible(pg) -> int:
    """Number of data rows currently rendered in the results grid."""
    return pg.locator('[data-testid="stDataFrame"] [role="row"]').count()

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1500, "height": 1000})
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(3000)

    pg.locator('input[type="file"]').set_input_files(
        [os.path.join(REC, f) for f in FILES])
    pg.wait_for_timeout(2000)
    pg.get_by_role("button", name="Extract data").click()
    pg.wait_for_selector("text=Download as spreadsheet", timeout=300_000)
    pg.wait_for_timeout(1500)

    before = rows_visible(pg)
    print(f"rows in grid after extraction: {before}")
    assert before > 0, "no table rendered after extraction"

    # The actual bug: click download, then check the page still shows the table.
    with pg.expect_download(timeout=60_000) as dl:
        pg.get_by_text("Download as spreadsheet").click()
    name = dl.value.suggested_filename
    pg.wait_for_timeout(3000)          # let the rerun settle

    after = rows_visible(pg)
    body = pg.inner_text("body")
    print(f"downloaded: {name}")
    print(f"rows in grid after download click: {after}")
    print(f"table still present:    {after == before}")
    print(f"success msg still there: {'Read 2 receipts' in body}")
    print(f"download btn still there:{'Download as spreadsheet' in body}")

    assert after == before, f"TABLE LOST: {before} rows -> {after} rows"
    assert "Download as spreadsheet" in body, "download button disappeared"
    assert "Read 2 receipts." in body, "status message disappeared"

    # Clicking twice must also be safe.
    with pg.expect_download(timeout=60_000) as dl2:
        pg.get_by_text("Download as spreadsheet").click()
    dl2.value.suggested_filename
    pg.wait_for_timeout(2500)
    assert rows_visible(pg) == before, "table lost on second download"
    print("second download click: table intact")

    # Changing the model is also a rerun; existing results should survive it.
    options = pg.locator('[role="option"]')
    pg.locator('[data-testid="stSelectbox"]').first.click()
    pg.wait_for_timeout(700)
    if options.count() > 1:
        options.nth(1).click()
    else:
        pg.keyboard.press("Escape")
    pg.wait_for_timeout(2500)
    assert rows_visible(pg) == before, "table lost when the model was changed"
    print("model dropdown change: table intact")

    # Adding a file changes the upload set, so stale results SHOULD clear —
    # showing numbers for a file the user just changed would be worse than
    # showing none.
    pg.locator('input[type="file"]').set_input_files(
        [os.path.join(REC, "invoice_ja_design.jpg")])
    pg.wait_for_timeout(3000)
    assert rows_visible(pg) == 0, "stale results survived an upload change"
    assert "Download as spreadsheet" not in pg.inner_text("body")
    print("upload set changed:     stale table cleared")

    b.close()

print("\n=== DOWNLOAD PERSISTENCE TEST PASSED ===")
