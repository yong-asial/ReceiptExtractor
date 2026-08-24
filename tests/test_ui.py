"""End-to-end UI test: upload 4 receipts, extract, download CSV."""
import os, sys, csv, io
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
# Override with APP_URL=http://127.0.0.1:8502 to test a second instance.
URL = os.environ.get("APP_URL", "http://127.0.0.1:8501")
FILES = ["receipt_us_cafe.jpg", "receipt_jp_store.jpg",
         "invoice_eu_supplier.jpg", "receipt_photo_gas.jpg",
         "receipt_ja_konbini.jpg", "invoice_ja_design.jpg"]
SHOTS = os.path.join(HERE, "shots"); os.makedirs(SHOTS, exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 1100})
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(3000)

    body = pg.inner_text("body")
    print("--- initial page text ---")
    print(body[:600])
    assert "Private Receipt Extractor" in body, "title missing"
    assert "Can't reach Ollama" not in body, "app could not reach Ollama"

    # Which model did the dropdown default to?
    try:
        sel = pg.locator('[data-testid="stSelectbox"]').first.inner_text()
        print(f"\n--- model selector default: {sel.strip()!r}")
    except Exception as e:
        print(f"selector read failed: {e}")

    pg.screenshot(path=os.path.join(SHOTS, "01-initial.png"), full_page=True)

    # Upload all four receipts at once.
    paths = [os.path.join(HERE, "receipts", f) for f in FILES]
    pg.locator('input[type="file"]').set_input_files(paths)
    pg.wait_for_timeout(2500)
    print(f"\n--- uploaded {len(paths)} files")
    pg.screenshot(path=os.path.join(SHOTS, "02-uploaded.png"), full_page=True)

    # Click Extract.
    pg.get_by_role("button", name="Extract data").click()
    print("--- clicked Extract data, waiting for results…")

    # Wait for the download button to appear (up to 4 min).
    pg.wait_for_selector('text=Download as spreadsheet', timeout=240_000)
    pg.wait_for_timeout(1500)
    print("--- results rendered")

    body = pg.inner_text("body")
    print("\n--- result page text ---")
    print(body[:1500])

    pg.screenshot(path=os.path.join(SHOTS, "03-results.png"), full_page=True)

    # Trigger the CSV download and inspect it.
    with pg.expect_download(timeout=60_000) as dl_info:
        pg.get_by_text("Download as spreadsheet").click()
    dl = dl_info.value
    out = os.path.join(HERE, "downloaded.csv")
    dl.save_as(out)
    print(f"\n--- downloaded: {dl.suggested_filename}")

    with open(out, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    print(f"--- CSV has {len(rows)} rows, columns: {list(rows[0].keys())}")
    for r in rows:
        print(f"    {r['File Name']:<26} {r['Vendor Name']:<22} {r['Date']:<12} "
              f"{r['Total Amount']:>10} {r['Currency']:<4} review={r['Needs Review']!r}")

    assert len(rows) == len(FILES), f"expected {len(FILES)} rows, got {len(rows)}"
    b.close()

print("\n=== UI TEST PASSED ===")
