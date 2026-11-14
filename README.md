# oculus-pdf

Scans `input/invoices/` and `input/statements/` for PDFs, skips lease/contract boilerplate pages before any model call, renders the remaining pages to images, transcribes each page with a vision model through the local `opencode` CLI, and writes one Markdown file per document plus a per-category `history.md`.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- The `opencode` CLI on `PATH`, with access to a vision-capable model

## Setup

```sh
uv sync
```

This installs the only runtime dependency: `pymupdf`, pinned to the 1.x line (`pymupdf>=1.28,<2`).

## Input and output

```
input/
├── invoices/
│   └── acme-2026-03.pdf
└── statements/
    └── visa-2026-03.pdf

output/
├── invoices/
│   ├── acme-2026-03.md
│   └── history.md
└── statements/
    ├── visa-2026-03.md
    └── history.md
```

- Only `.pdf` files (case-insensitive) directly inside each category folder count. Dotfiles and subfolders are ignored.
- Missing category folders are fine; they are treated as empty.
- The categories are fixed: `invoices` and `statements`.
- The Markdown file is named after the PDF stem. The `File` column in `history.md` keeps the `.pdf` extension.

## Usage

```sh
uv run oculus-pdf [--input ./input] [--out ./output] [--dpi 150] \
  [--model opencode/deepseek-v4.1-flash-free#high] [--concurrency 4] [--force]
```

| Option | Default | Description |
| --- | --- | --- |
| `--input` | `./input` | Directory containing the `invoices/` and `statements/` folders |
| `--out` | `./output` | Output directory |
| `--dpi` | `150` | Render resolution in DPI |
| `--model` | `opencode/deepseek-v4.1-flash-free#high` | Model as `provider/model[#variant]`, run through `opencode` |
| `--concurrency` | `4` | Number of parallel transcription requests |
| `--force` | off | Ignore history and reprocess every document |

## How it works

1. Check that `opencode` is on `PATH`.
2. Discover documents in `input/invoices/` and `input/statements/`.
3. For each document, compute its SHA-256 and look it up in that category's `history.md`.
4. Skip the document when its file name and hash match an entry whose status is `ok`; otherwise process it.
5. Read the PDF text layer of every page with PyMuPDF (`get_text`) and check it with a free heuristic. Pages detected as lease/contract boilerplate are skipped: they are never rendered, never sent to the model, and absent from the Markdown. Pages with no text layer (scans) cannot be classified and are processed normally. If reading the text layer fails, nothing is skipped.
6. Render each remaining page to PNG bytes and pass them to `opencode run --file` through a short-lived temporary file. At most `--concurrency` requests run at once, with at most `--concurrency` x 2 pages in flight. Temporary files are deleted afterwards.
7. Write the document's Markdown, then update that category's `history.md` with an atomic write.
8. Print a summary.

Documents are processed one at a time, invoices first and then statements, each category sorted by file name case-insensitively. A failed page is retried twice, with 1s and then 2s of backoff, before it is recorded as failed; the remaining pages continue.

## Skipped contract pages

Before rendering, each page's text layer is checked by a heuristic in `contract.py`. A page counts as lease/contract boilerplate when it has at least 400 words (split on whitespace) and matches at least 3 distinct markers from a fixed list: lessee, lessor, indemnif*/indemnit*, hereby, "this agreement", "terms and conditions", sub-lease/sublease, warranty/warranties, liability/liabilities, and "governing law".

On the sample 4-page invoice, the two lease pages had 2291 words and 8 markers; the two invoice pages had 224 and 42 words and 0 markers.

There is no flag to turn this off. The thresholds are constants in `contract.py` (`WORD_THRESHOLD` and `MARKER_THRESHOLD`).

The heuristic can produce false positives: a long fine-print page that contains 3 or more of those terms (for example a statement's terms page) will be skipped silently from the Markdown. It is still counted in `Pages Skipped` in `history.md` and in the run output, so the omission is visible there.

## Document format

Each document is a single Markdown file with one section per page that was sent to the model, in page order:

```markdown
# acme-2026-03

## Page 1

<Markdown for page 1>

## Page 2

<Markdown for page 2>
```

Skipped pages are absent: no heading and no placeholder. The remaining pages keep their original page numbers, so the file can jump from `## Page 1` to `## Page 3`. A document whose every page is skipped is just `# <stem>`.

Headings inside a page's Markdown are demoted by two levels (`#` becomes `###`, `##` becomes `####`, capped at `######`) so they always nest below `## Page N`. Headings inside fenced code blocks and non-heading `#` lines are left alone.

A page that could not be transcribed keeps its section heading with a `(failed)` suffix:

```markdown
## Page 3 (failed)

*Transcription failed: opencode exited with code 1*
```

The error is from the last attempt, with newlines collapsed to spaces.

## history.md

Each category has its own `output/<category>/history.md`:

```markdown
| File | SHA256 | Pages OK/Total | Pages Skipped | Status | Input Tokens | Output Tokens | Timestamp (UTC) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| acme-2026-03.pdf | 3f9c...a1 | 2/2 | 2 | ok | 41234 | 1876 | 2026-11-13T09:15:00+00:00 |
```

- A document is skipped only when its file name and SHA-256 match a history entry and the status is `ok`.
- A changed file with the same name, or any entry that is not `ok`, is reprocessed in full on the next run. There is no per-page resume. Its existing row is replaced, not duplicated.
- `--force` reprocesses every document, regardless of history.
- `Pages OK/Total` counts only the pages actually sent to the model. `Pages Skipped` counts the contract pages skipped. Status is `ok` only when every page sent to the model succeeded, so a document whose pages were all skipped is `ok` with `0/0`.
- Legacy 7-column history files are still read, with skipped pages treated as 0. They are rewritten in the 8-column format the next time that category's history is written. Documents already processed keep their previous Markdown until they are reprocessed (a changed file or `--force`).
- An unopenable PDF is recorded as `failed` with `0/0` pages and `0` skipped. No Markdown file is written, and the run output shows only the `0/0 pages, failed, 0 skipped` entry; no failure reason is stored.

## Run output

Each processed document prints one line:

```
processed: invoices/acme-2026-03.pdf (2/2 pages, ok, 2 skipped)
```

The page counts cover only pages sent to the model, and the last number is the count of contract pages skipped. Unchanged documents print `skip: <category>/<file> (unchanged)`.

After a run with PDFs, a summary prints:

```
processed: 3, skipped: 1, failed: 0
```

These are whole-document counts. Here `skipped` means unchanged documents, which is a different thing from skipped pages.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Every document processed in this run fully succeeded. A run with nothing new also exits `0`; it prints `nothing to process` when there are no PDFs, or skips the unchanged files. |
| `1` | At least one document processed in this run had a failed page or could not be opened. Skipped documents do not affect the code. |
| `2` | Usage error: `opencode` is not on `PATH`, or the input directory is missing. |

## Token counts

Counts come from opencode's per-step `input` and `output` usage and are recorded per document in `history.md`. Each call carries roughly 7k tokens of opencode's own prompt overhead. Cached input tokens (`cache.read`) are not counted, so input totals undercount when the prompt cache is hit.

## Development

```sh
uv run pytest
```

The tests stub `opencode`, so no network access or installed `opencode` binary is needed.

- `src/oculus_pdf/cli.py` - argument parsing and orchestration
- `src/oculus_pdf/contract.py` - lease/contract page detection
- `src/oculus_pdf/discover.py` - finding documents and hashing
- `src/oculus_pdf/history.py` - reading and writing `history.md`
- `src/oculus_pdf/output.py` - Markdown writer
- `src/oculus_pdf/render.py` - page counting, text-layer extraction, and PNG rendering
- `src/oculus_pdf/transcribe.py` - opencode call, retries, token parsing

`contract.is_contract_page` consumes the text from `render.page_text`. `render.parse_page_range` remains in the module and is covered by tests, but the CLI does not use it.

## Limitations

- Markdown output only.
- The two categories are fixed; there is no configuration for adding others.
- The PDF text layer is used only to detect and skip lease/contract pages, never for transcription or cross-checking.
- Tables are not merged across pages.
- Model errors are possible. In a test on a 4-page invoice PDF, the structured invoice fields and totals matched the PDF text layer, but dense contract small print came back reworded or invented, and two pages with identical text were transcribed differently. Contract pages are now skipped before transcription, which avoids this specific failure, but other dense small print can still be reworded. Verify numbers and legal text against the source.
- Small footers, such as print dates and page counters, can be dropped.
- Pages are sent to whichever provider the chosen model uses, so check that provider's data-handling policy.
- Processing is slow per page: transcribing all 4 pages of the sample invoice took about two minutes in testing; with its two contract pages skipped, the run took about 15 seconds.
- `input/` is not git-ignored, so source PDFs would be committed unless you add an ignore rule. `output/` is ignored.
