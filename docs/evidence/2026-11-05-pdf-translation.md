# Complete PDF book: Git from the Bottom Up

Historical report. Current requirements and boundaries are in the [specification](../specification.md); decisions and cancellations are in the [Decision log](../decision-log.md). References to later stages describe the state at the time of the experiment.

On 05.11.2026, at the user's request, translation of **the entire original PDF** of John Wiegley's *Git from the Bottom Up* was checked: **31 pages, 262 translatable blocks**, without manual translation edits. Confirmed projection and layout defects were fixed. The final PDF was built, the complete translation compared with the original, and all pages viewed after rasterization. This completes the two P1 items for a real PDF book within the checked document class; it does not accept arbitrary PDF layouts.

## Material and conditions

The original is the [author's PDF](https://ftp.newartisans.com/pub/git.from.bottom.up.pdf), with **2 December 2009** on the title page and Git **1.5.4.5**. The downloaded PDF was used with its original fonts, forms, diagrams, shadows, and tables; the book was not retypeset into a simplified fixture before translation. Size: 811 094 bytes, SHA-256:

`22476f2939a04255b82b8f7cb7ad3290b6ca414412c34ffcfae76dc4a7917dda`.

The PDF's second page specifies **CC BY-SA 3.0 US**. It, the author's notices, and references remain in their original language. The Russian derivative is distributed under the same terms, with John Wiegley attribution and a brofessor translation notice in metadata and the accompanying README. A newer license from other editions was not substituted for this PDF's license. Historical Git claims and commands were translated/preserved according to the original, without updating them to modern Git.

The source has an incorrect pointer to unused object 269: pypdf reports `Ignoring wrong pointing object 269 0 (offset 0)` and recovers reading. Coverage of all pages/text objects was checked separately; the original itself was neither repaired nor modified.

Stable `/Users/demets/.local/bin/codex` **0.162.1**, **gpt-6.1-sol** requested and confirmed, reasoning effort `none`, standard subscription authorization. No paid API/fallback, OCR, layout model, or new weights were used. Experiment settings were isolated through XDG in an ignored directory. Audio and user projects were untouched.

## Defects found and fixes

| Defect on the book | Change |
|---|---|
| Paragraphs broke into words/styles; indented footnotes lost coherence | Projection 2 groups by baselines, joins hanging-indent paragraphs, and preserves inline styles/colors/superscript footnotes with protected markers |
| Private Unicode font glyphs became squares; hyphenation and ligatures damaged source text | The document's custom Encoding/Differences and ToUnicode were mapped; verifiable oldstyle digits/ligatures and discretionary hyphens are supported. Unknown PUA characters are rejected |
| PDFium page regeneration changed untouched encodings; nested diagram text remained beneath translation | For projection 2, pypdf removes only selected text strings in content streams, including Form XObjects. Numeric TJ cursor movements remain in their place; graphics, original fonts, and other string positions are preserved |
| The table of contents collapsed into a paragraph; a long Russian line shifted a caption relative to its number | Line boundaries are protected; numbers move with the corresponding line. Link rectangles, where present, follow the line while retaining their destinations |
| Mixed typography set the entire paragraph size from a small HEAD fragment | Base size uses the paragraph's main size; code stays protected |
| An earlier paragraph occupied the next one's space, causing late overflow | First choose a readable size within the paragraph's own area, then allow denser spacing and bounded local displacement with overlap checks |
| Long words did not fit narrow cells | Pinned Pyphen 0.18.1; Russian dictionary hyphenation supplements ReportLab for long words. Every line's actual width is checked |
| Soft hyphens in every word made words join when fonts changed | Add explicit soft hyphens only to words that do not fit. A regression checks spaces between ordinary/italic text and inline code; the audit now checks word boundaries too |
| A git-commit command beneath a diagram caption prevented translation growth | The command remains an immutable original and moves with its caption; old text is actually removed and the new area is reflected in the map |
| A caption inside a cloud approached an arrow and split mid-word | Centered nodes get internal padding, retain the label center, and wrap whole words; size is reduced within allowed limits when needed |
| A gap between glyphs split the -f parameter | Adjacent monospaced fragments without an original space form one protected token again |

New jobs pin **pdf_projection=2**; existing projection 1 jobs continue using their previous projection. Translation workflow remains **4**, shared by EPUB and PDF. Composite Type0 font codecs, shared text Form XObjects, transformed forms, and other unsupported structures fail explicitly before model calls. Cancellation checks also run inside stream parsing/rewriting.

## Real translation and recovery

Main job **`4cf651da690c4123`**, saved **r1**: **262 blocks, 64 senses / 542 occurrences**, without manual editorial changes. Final translation batches cover 40, 38, 62, 41, 46, and 35 blocks. The full glossary and recurring-term review were each accepted in two batches.

A total of **14 runner calls** were recorded, of which **10 checkpoints belong to the final result**. Two calls were cancelled while fixing the projection; one returned response was rejected for an empty unstyled span containing an English article; one previously accepted 40-block batch was replaced after table-of-contents lines were protected. The article was moved inside the neighboring styled span so its absence in Russian would not require inventing an extra word. The general nonempty-content contract was not weakened.

Total duration of all calls: **1 689.703 s**; final checkpoints: **1 241.093 s**. This is runner-call time, **not continuous time to a finished book**: fixes and checks took place between attempts. After saving r1, discovered overflows were fixed in the local renderer, without repeating translation/glossary generation or changing the revision. An intermediate build error did not publish an incomplete PDF.

Final local build **`73ae55c49e504815`** passed through the ordinary worker in **2.558 s**, with model calls prohibited by the control harness: **0 calls**. The original draft r1 and earlier builds remain saved. SHA-256 of draft-r1.json:

`5877d9342bdfec8b07c09b3dae0e7084f7d404aaa028661a325d1c937e73310a`.

## Content and visible result

The agent compared **all 262 pairs** of source text and final r1, including the replaced opening batch. Checks covered blob/tree/commit/index definitions, head/HEAD/branch/tag distinctions, ^n and ~n indices, two-/three-dot ranges, reset --mixed/--soft/--hard, rebase consequences for published branches, stash/reflog, numerals, and negations. No material omissions or introduction of opposite meanings were found on this book.

Local language roughness remains: cumbersome “извлечение версии” for checkout and a long stash translation; one “в репозитории” form in the index definition is grammatically awkward, but the distinction's meaning is retained. The source itself extracts one file ligature as `!le`; the model restored “файла” from diagram context. Exhaustive terminology, editorial quality, and independent expert proofreading are not claimed. 542 anchors do not prove that every occurrence of every term was found.

**All 31 pages** were rasterized with PDFium and Poppler. Every page was viewed on contact sheets, with problematic regions additionally viewed at full size. Separate checks covered title/navigation, definitions and footnotes, diagrams on pages 4/12/20, option tables 13/14/18, graph spreads 15–19/25, the ending, and links. The last node fix was viewed again in Poppler. No arrow overlaps, old-text overlays, missing lines, or squares instead of letters were found in the final file. The font was replaced with DejaVu Sans while preserving recognized styles and colors; exact source typography is not reproduced.

Independent `tools/check_pdf_translation.py` reads the **actual PDF** and checks all 262 regions, 352 retained regions, original numeric values, images, and native vector-path bounds. Actual PDFium discretionary hyphens are handled without ignoring lost letters/words/spaces. The latest file has **0 findings**. **44 original links** were also checked: counts and destinations are unchanged. The original has no outline or table-of-contents links; moving a clickable table-of-contents area is checked by a separate synthetic regression, not attributed to this book. Images are byte-preserved at the extracted-content level. Comparing path bounds does not prove equality of every vector property, so visual inspection was performed separately.

## Checks and dependencies

The full offline suite after fixes: **565 passed**, including **27 PDF checks**. Ruff check/format and diff check pass. Checks exercise real boundaries: mixed spans/footnotes/spaces, named glyphs, Form text removal without duplicates, retention of the next Tj cursor, shared-Form/Type0 refusal, a table-of-contents row with its number/link after wrapping, moving an unchanged command, CLI options without an inserted space, text inside a node, damage to the actual PDF, recovery and model-free building, cancellation, and CLI/UI. Previous projection 1 protection remains a separate case; tests were not removed.

The new external component is [Pyphen 0.18.1](https://github.com/Kozea/Pyphen/releases/tag/0.18.1), pinned in pyproject/uv.lock. MPL-1.1 was selected from its code's triple license; dictionaries have their own notices. The Russian dictionary was compared byte-for-byte with LibreOffice; its README, absent from the wheel, is saved in [LICENSES/Russian-hyphenation.txt](../../LICENSES/Russian-hyphenation.txt). [Full details](../../THIRD_PARTY_NOTICES.md). pypdfium2/PDFium, pypdf, ReportLab, and DejaVu retain their previous pinned versions. An updated wheel was built; checks cover PDF modules, fonts, the new notice and pinned Pyphen metadata, and absence of books/outputs. No new framework, queue, or server was added.

## Local files and reproduction

Ignored `outputs/pdf-book-2026-11-05/` contains the original, `projection.json`, `calls.json`, model-returned batches, a workspace with checkpoints/revisions, `audit-rebuild.json`, `local-rebuild-final.json`, `final-proof.json`, page PNGs, and licensing material. `result.json` retains the **historical failure on the first table-of-contents overflow**; the final status/hashes are in final-proof.json.

The finished copy is `git-from-the-bottom-up-ru.pdf`; the last build's original is `workspace/jobs/73ae55c49e504815/translation-r1.pdf`. Size: 3 096 401 bytes, SHA-256 **`53611191b6861e400a4f38aa2e645bd34e214d94b59fc1bc23ed8d4c3701b7c9`**. The hash is also in final-proof.json and audit-rebuild.json. After the last fix, all 31 pages were rasterized again: only 4 and 20 changed, and both were rechecked in Poppler; remaining PNGs were byte-identical to those already viewed. User text, third-party books, and generated files were not added to the public repository.

```sh
# A new real run, only when a fresh translation is needed:
BROFESSOR_CODEX_BIN=/path/to/stable/codex uv run --no-sync python tools/probe_pdf_translation.py \
  --source /path/to/book.pdf --model gpt-6.1-sol --output outputs/pdf-book-next

# Existing book: audit the latest local export, with no model calls:
uv run --no-sync python tools/check_pdf_translation.py \
  --workspace outputs/pdf-book-2026-11-05/workspace --job 4cf651da690c4123
```

No new model run is needed to recheck an already saved translation. The verified class is horizontal decodable text, simple fonts, ordinary pages/columns/cells, and unique Forms with an identity matrix. Scans, translation of raster text, complex inline mathematics, arbitrary geometry/layers, and large textbooks are not accepted. A document that does not fit or is unsupported fails explicitly, without silently switching to cloud processing or losing text. Measuring download speed in the ordinary user's browser remains a separate earlier limitation; browser downloading was not repeated in this continuation.

## First synthetic page

Historical snapshot of projection 1. A later continuation checked [a whole PDF book and fixed its layout](2026-11-05-pdf-translation.md); the current projection and support boundaries are described there.

05.11.2026. First check of the PDF path selected in [D017](../decision-log.md#d017-05112026--bounded-local-pdf-translation). The initial PDF path through shared worker/CLI/UI was implemented and checked. This is **one synthetic page**, not acceptance of a whole PDF book or complex publishing layout. Previous EPUB results and jobs were preserved. Speech was not run.

### What was implemented

`pdf_translation.PdfBook` extracts addressable text objects from the saved original: SHA-256, page number, original region, text, size/style/color. Neighboring lines of one style are joined into paragraphs. The model translates only text in the existing bounded batches; it does not control graphics or coordinates.

Local assembly removes precisely the translatable text objects through PDFium, leaving original images, vector lines, and protected text. It does not use white rectangles over the original or page rasterization. ReportLab places translation with embedded DejaVu Sans. Columns, neighboring text, cell lines, and illustrations constrain available space. Size is checked using font metrics; the lower limit is 80% of the original, with ordinary text never below 9 pt and originally small labels/footnotes retaining their size. Text that does not fit raises an error naming the source page/region, and the previous file is preserved.

Isolated recognized formulas, code, and numeric/symbolic objects stay original and are listed in UI and metadata. Ordinary monospaced prose is translated too: a font name alone does not make text code. Text inside raster images is not translated.

`translate_pdf` and `render_pdf` use existing SQLite/jobs/drafts/checkpoints/task models without a new database schema, server, or queue. CLI `translate SOURCE_ID` selects EPUB/PDF from the original; the UI provides a separate clear text-layer PDF option. Optional glossary, progress, cancellation/resume, revisions, editor recovery, local rebuilding, current task models, and regeneration in the same group are available. The shared sense-correction/manual-phrase retention mechanism is reused. This experiment made no real model call for PDF sense correction specifically; its structural rules are covered by existing shared-terminology tests.

Every PDF export has `layout-rN.json`: a mapping of translation IDs, pages, original/final regions, font sizes, retained text, and actual renderer versions. The UI shows the original quotation with page/coordinates. Rendering pins the revision on submit; later edits do not change it. Cancellation is checked during page parsing/assembly and before atomic publication.

### Component selection and licenses

Rather than installing previously assessed BabelDOC, a small local path without a layout model or weight downloads was selected. This is a decision for the initial supported PDF class, not evidence of superiority over BabelDOC on complex documents. Its own integration and resources remain unverified.

Stable PyPI releases [pypdfium2 5.14.0](https://pypi.org/project/pypdfium2/5.14.0/) and [ReportLab 5.1.0](https://pypi.org/project/reportlab/5.1.0/) are pinned. The former installs PDFium **156.0.8076.0**; helpers are under BSD-3-Clause / Apache-2.0, and the native wheel includes full PDFium/dependency `BUILD_LICENSES`, including FreeType, ICU, and libjpeg-turbo. ReportLab is BSD. No AGPL components were added. Other verified runtime versions: Python 3.12.13, pypdf 6.21.4.

The package includes four unchanged styles of **DejaVu Sans 2.37** with permission to embed/distribute. [License](../../LICENSES/DejaVu.txt), [official source and SHA-256](../../src/brofessor/infrastructure/formats/fonts/README.md), [attribution](../../THIRD_PARTY_NOTICES.md). Installation/rendering does not depend on system fonts or the agent runtime. A wheel was built and all four TTFs and the license checked. The package was extracted into a temporary directory outside the checkout, imported from there, and actually built a Cyrillic PDF with its own fonts.

Rationale: [PDFium API, object extraction/removal, and threading restrictions](https://pypdfium2.readthedocs.io/en/stable/python_api.html), [Unicode TrueType in ReportLab](https://docs.reportlab.com/reportlab/userguide/ch3_fonts/). PDFium disallows simultaneous threaded calls even for different documents; core operations are serialized by a process-wide `RLock`, while the worker remains a separate process.

### Real run

Material: the original MIT generator `tests/pdf_helpers.py`, page **Reliable sensor ingestion**, Letter 612 × 792 pt. Two columns, headings, four table cells, a footnote, raster diagram, formula `V = Q / C`, code `commit(record_id)`, and a page number. This is an original text-layer PDF, not an EPUB conversion as part of translation. No third-party books or generated results were added to the repository.

The projection contains **14 translatable blocks** and **3 retained objects**. It produced **21 senses / 33 occurrences**. Original SHA-256: `1a7a4bb26799d156fb9643b82bf2a780ae318384cea8636aebd4a637067d5599`.

Stable `/Users/demets/.local/bin/codex` **0.162.1**, runner model **gpt-6.1-sol** requested and confirmed, reasoning effort `none`. Standard subscription authorization was used; no paid API or fallback was connected. Only synthetic text was transmitted. User settings were isolated through XDG inside the ignored experiment directory.

| Stage | Time, s | Prompt characters | Schema characters | JSON-response characters |
|---|---:|---:|---:|---:|
| Automatic glossary | 61.736 | 2 742 | 1 456 | 7 646 |
| Translation and anchors | 48.508 | 15 057 | 1 052 | 6 664 |

The full worker pass took **110.308 s**, job `539ecef679b54c5a`, r1, with no manual editorial edits. Both calls include the standard authorization check. This is one run; book speed and cost/tokens cannot be inferred from these numbers. Separate local r1 rebuild: `b6c2fd26a6064da1`; it makes no model call and adds renderer metadata and the correct preserved-formula label.

### Content and visible result

The agent compared **all 14 blocks** of the source and r1. Preserved: no acknowledgment before durable persistence, possible loss of an unacknowledged record, no duplicate on retry, limitation of results to one setup, and no protection from storage-medium destruction. `hydraulic head` was not confused with a manager, nor `database log` with a wooden log. 3.5 m, 20 ms, and 5 V/s were retained with Russian units. No omissions or changed negations were found in this material.

The glossary is not exhaustive: not every contextually correct word received its own sense/anchor. The durable-persistence wording in a paragraph and table is cumbersome. This is an understandable technical draft with local linguistic roughness, not publisher-level proofreading; no independent editor participated.

The original, reconstruction with English text, and Russian PDF were fully rendered by Poppler; the Russian result was viewed at 110 dpi. Cyrillic and styles are readable, wraps stay within columns/cells, and formula/code and diagram are retained. No overlaps, truncation, or squares instead of letters were found. Body text stayed at 11 pt, column headings at 12.25/12.5 instead of 13 pt, book title at 19 pt, caption at 9 pt, and the footnote at its original 8 pt.

`tools/check_pdf_translation.py` independently reads the **finished PDF**, extracts every final region's text, and compares it with the saved revision. It also checks original numerical values, protected text, image content, page count, and native vector-path bounds. The original export and local rebuild have **0 findings**. A check with deliberately damaged PDF content detects text loss even when draft/layout remain valid and unchanged. Bounds comparison does not prove all vector-graphics properties identical; visual inspection was separate.

Real Streamlit at isolated `127.0.0.1:8557` was opened in a browser: r1, the original with page/coordinates, glossary with original quotations, local building, and PDF downloading are visible. The download button does not cause a rerun. Download speed in the ordinary user's browser was not measured; the problematic `waitForEvent(download)` was not called. The QA server was stopped.

### Boundary checks

Final full offline run: **552 passed**, including **14 PDF checks**. Ruff check/format and `git diff --check` pass. Coverage includes column/table/footnote projection, original and images, explicit rejection of rotation/image-only/Form/invisible/clipped text, overflow, missing glyphs, cancellation after temporary writing but before publication, monospaced prose, hyperlinks/outlines, fault/resume with glossary reuse, CAS editor/pinned render, no model during building, CLI/UI parity, regeneration, and damage to the actual PDF. These are offline contracts, separate from the two real calls and page viewing. Existing shared-terminology tests retain protection for targeted corrections and manual phrases; tests were not deleted.

### Files and reproduction

Local ignored directory: `outputs/pdf-translation-2026-11-05/`. `source.pdf`, `projection.json`, `identity.pdf`, `calls.json`, `result.json`, `local-rebuild.json`, `audit.json`, `audit-rebuild.json`, page PNGs, and `workspace/`. Automatic original PDF: `workspace/jobs/539ecef679b54c5a/translation-r1.pdf`; current local rebuild: `workspace/jobs/b6c2fd26a6064da1/translation-r1.pdf`. SHA-256 of the latter: `d410adac70dc4a37579cf6b4bfd0b9990f193db2daefc8b97e58da0a6b21f251`.

```sh
BROFESSOR_CODEX_BIN=/path/to/stable/codex uv run --no-sync python tools/probe_pdf_translation.py \
  --model gpt-6.1-sol --output outputs/pdf-translation-next
uv run --no-sync python tools/check_pdf_translation.py \
  --workspace outputs/pdf-translation-2026-11-05/workspace --job 539ecef679b54c5a
uv run --no-sync pytest -q tests/test_pdf_translation.py tests/test_pdf_workflow.py tests/test_pdf_audit.py
```

The probe uses the existing worker with an OS-lock, saves calls, and supports continuation through existing checkpoints. New generation of the same original need not be repeated without a discovered defect.

### Supported-class boundaries

The early path targets decodable horizontal text directly on pages with ordinary coordinates. It explicitly rejects scans/image-only pages, encryption, forms/signatures, rotation/cropping, nested Form XObject text, clipping, invisible text, unsupported glyphs, and areas without space for a readable translation. Source font families are replaced with embedded Sans while retaining recognized style and color; identical source typography is not promised. Automatic line grouping is not a full semantic PDF parser.

Arbitrary inline formulas with superscripts/subscripts, rich mixed typography, and complex tables have not been separately accepted. Overflow is not solved by losing text or automatically switching renderers; such files are not published. Hyperlinks/outlines were checked by a local contract on a separate two-page fixture, not a real model run on a book. Meaning and appearance of a complete real PDF, long recovery, and different book types remain open in P1. The current check does not justify closing those items.
