# Private Receipt Extractor

Reads receipt and invoice images with a local vision model and exports a CSV.
Nothing leaves the machine.

## Requirements

- **Ollama 0.4 or newer.** Older versions cannot load vision models at all —
  they download fine, then fail with `unknown model architecture`. Check with
  `ollama --version` and reinstall from [ollama.com](https://ollama.com) if
  needed. Reinstalling keeps the models already on disk.
- Python 3.9+

## Setup

1. Install [Ollama](https://ollama.com) and make sure it is running.
2. Download a vision model:
   ```
   ollama pull qwen2.5vl:7b     # 6 GB — best accuracy
   ollama pull qwen2.5vl:3b     # 3.2 GB — same scores, for 8 GB machines
   ```
3. Install the Python libraries. From the repository root:
   ```
   python3 -m venv .venv
   .venv/bin/pip install -r app/requirements.txt
   ```

## How the code is laid out

Five files, each one thing, each explaining itself at the top:

| File | What's in it |
|---|---|
| `settings.py` | Fields, prompt, size limits — the things you'd change |
| `uploads.py` | The upload gate, and preparing an image for the model |
| `reader.py` | Ollama: listing vision models, and reading one receipt |
| `tidy.py` | Normalising amounts and dates, and the Needs Review flags |
| `app.py` | The Streamlit page, and nothing else |

Nothing but `app.py` imports Streamlit, so the other four can be imported and
tested on their own — which is what the test scripts do.

## Run

From the repository root:

```
./run.command
```

That starts Ollama if it isn't already running, then opens the app at
http://localhost:8501. Drop in receipt images, click **Extract data**, then
download the CSV.

Or directly:

```
.venv/bin/streamlit run app/app.py
```

## Note on models

`llama3.2-vision` does **not** work on current Ollama versions — the `mllama`
architecture was removed and loading it fails with
`unknown model architecture: 'mllama'`. Use the `qwen2.5vl` models instead.

## Tested

Six synthetic documents, 8 fields each (48 total):

| # | Document | Tests |
|---|---|---|
| 1 | US café receipt | USD, `MM/DD/YYYY` |
| 2 | German invoice | EUR, `DD.MM.YYYY`, `1.725,50` decimal comma, issue vs due date |
| 3 | Fuel receipt as a bad phone photo | 6° rotation, 72% brightness, blur, sensor noise |
| 4 | Romanised Japanese konbini receipt | JPY, no decimals, `YYYY/MM/DD` |
| 5 | Japanese retail receipt (領収書) | Japanese script, `年月日` date, 現金 |
| 6 | Japanese business invoice (請求書) | Japanese script, 発行日 vs お支払期限, 銀行振込 |

| Model | Fields correct | Size |
|---|---|---|
| `qwen2.5vl:7b` | **48/48 (100%)** | 6.0 GB |
| `qwen2.5vl:3b` | **48/48 (100%)** | 3.2 GB |
| `granite3.2-vision` | 19/48 (40%) | 2.4 GB |
| `llama3.2-vision` | fails to load | 7.8 GB |

## Model list

The dropdown offers only models Ollama reports as vision-capable, so text-only
models (`llama3`, `mistral-openorca`) and embedding models (`nomic-embed-text`)
never appear. `llama3.2-vision` is excluded too: it advertises a `vision`
capability but its `mllama` architecture no longer loads. A caption under the
dropdown says how many installed models were hidden.

`granite3.2-vision` is kept in the table as a cautionary case: it misreads
invoice totals in a way that stays internally consistent (so the arithmetic
check cannot flag it), and on the Japanese receipt it hallucinated the vendor
name 株式会社サクライト in place of 株式会社サクラマート.

## Tests

```
.venv/bin/python tests/test_upload_limits.py            # upload gate, no model needed
.venv/bin/python tests/test_edge.py     qwen2.5vl:7b   # unit tests + live model checks
.venv/bin/python tests/test_extract.py  qwen2.5vl:7b   # accuracy vs ground truth
```

Browser tests (need the app running and `pip install playwright`):

```
.venv/bin/python tests/test_ui.py                 # upload -> extract -> CSV
.venv/bin/python tests/test_download_persists.py  # table survives a download click
```

`tests/make_receipts.py` and `tests/make_receipts_ja.py` regenerate the test
images and `ground_truth.json`.

Non-Latin scripts: the CSV is written as `utf-8-sig` so Excel and Numbers open
Japanese correctly. Note that spreadsheet apps strip leading zeros from invoice
numbers like `000517` — set the column format to Text on import if that matters.
