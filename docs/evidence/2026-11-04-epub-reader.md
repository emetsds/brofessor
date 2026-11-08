# EPUB 2/3 and a whole book in a reader

Historical report. Current requirements and boundaries are in the [specification](../specification.md). Decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state on the experiment date.

04.11.2026. P1 continuation after [contextual terminology](2026-11-04-book-terminology.md). No application dependencies were added. EPUB.js, JSZip, and EPUBCheck are used only for QA.

## Format changes

Reflowable EPUB 2.0 with NCX and EPUB 3.x with XHTML navigation and supplementary NCX are supported. The spine, nested NCX structure, navigation targets, resources, and original XML prefixes are preserved. docTitle/navLabel and guide titles are translated. dtb:uid is aligned with the new OPF identifier. Names in docAuthor are preserved.

Standard XHTML 1.0 Strict/Transitional, XHTML 1.1, HTML, and NCX declarations are allowed through a closed list. External DTDs are not read. Named XHTML characters are resolved once using Python's standard table. Internal subsets, entity definitions, and unknown DTDs are rejected, including in UTF-16. CDATA meaning, comments, namespace scopes, and QName metadata values are preserved. Fixed layout, scripted content, media overlays, encryption/obfuscation, and signatures remain rejected.

A defect was found in the earlier assembly: EPUBCheck accepted EPUB 3 with prefixes added by ElementTree, but EPUB.js 0.3.88 remained at archive opening without a table of contents or content. A local rebuild of the accepted revision with the new serializer opened successfully: four TOC entries, Cyrillic, a table, SVG, MathML, and code. No inference was repeated. A regression test checks preservation of the original XML-tag spelling in addition to the namespace-expanded tree.

Legacy layout with a long `<big>` element and paragraphs separated by double `<br>` is split into model paragraphs without changing the XML. Projection 2 adds this splitting and license exclusions. Projection 3 additionally protects text function calls `square(...)`, `cube(...)`, `square_root(...)`, and `cube_root(...)` as immutable fragments. New jobs pin `epub_projection=3`. Historical jobs without the parameter use projection 1. Projection 2 jobs retain it. Render, term correction, and regenerate do not reproject accepted blocks, glossaries, or revisions.

In the new projection, `epub:type="copyright-page"` and explicitly marked pg-boilerplate `pg-header`/`pg-footer` remain in their original language. The exclusion list is recorded in EPUB artifact metadata, and the UI reports its count. Arbitrary unmarked legal sections are not recognized automatically.

## Source

The complete W. Stanley manual **Instruction for Using a Slide Rule**, [Project Gutenberg No. 20214](https://www.gutenberg.org/ebooks/20214), [illustrated EPUB](https://www.gutenberg.org/ebooks/20214.epub.images). The source states Public domain in USA. This is not a claim about its status in every country. The original, model responses, and results stay in ignored `outputs/epub-whole-book-2026-11-04/`.

Snapshot: 3 688 132 bytes, SHA-256 `8fc5977f1b78f7df2cec62fc1fc08826c622c05fab2c066420bffd944e7d7dcc`. EPUB 2.0: cover and main XHTML in the spine, NCX, 61 JPEG + 1 PNG, and two CSS files. The source has 8282 whitespace-counted words, including 3059 words in two retained PG notices. The main book with transcriber's notes is about 5200 words. All 213 blocks were extracted, with a maximum of 1033 characters. This is a short but complete technical book. The experiment does not establish quality on large modern textbooks.

Original and unchanged-text assembly: **EPUBCheck 5.4.0 — 0 errors / 0 warnings**. Independent `tools/check_epub_translation.py`: 66 immutable resources retained, 134 local links checked, 5 external links left without fetching them, and no findings. The complete XHTML text before/after this assembly was compared separately: no differences.

## Reader and reproducibility

Official [EPUB.js 0.3.88](https://github.com/futurepress/epub.js/releases/tag/v0.3.88), BSD-2-Clause, and [JSZip 3.10.1](https://github.com/Stuk/jszip/releases/tag/v3.10.1), MIT/GPL-3.0 dual license (MIT selected for QA). Builds were obtained from the official npm registry, hosted locally, and excluded from dependencies/distribution. SHA-256 of `epub.min.js`: `c7a842da856d511938cba1ba64d90743c318ac02c13e47bc84ae4834fe94c945`; `jszip.min.js`: `acc7e41455a80765b5fd9c7ee1b8078a6d160bbbca455aeae854de65c947d59e`. License files are retained alongside them.

`tools/epub_reader.html` is copied alongside these JS files named `epub-0.3.88.min.js` and `jszip-3.10.1.min.js`. A temporary loopback HTTP server serves the page. `?epub=../FILE.epub` opens the ZIP itself. The reader has a table of contents, spine, page navigation, search, and CFI positions. Book scripts are disabled. This is EPUB.js acceptance, not acceptance on every hardware reader.

## Full model run and proofreading

Stable Codex CLI **0.162.1**, `gpt-6.1-sol`, subscription authorization, process-local `BROFESSOR_CODEX_BIN=/Users/demets/.local/bin/codex`. Job `fe13748d44ce4c6d`, workflow 2 / projection 2, was created through the regular `translate` CLI and completed in an independent worker in **989,284 s (16:29)**. Six real calls: two glossary packages and four translations. All 213 blocks were accepted without truncation, with **53 senses / 165 source occurrences**. All six checkpoints were saved. Main-application settings and the paid API were not used.

All 213 source/translated blocks were checked, including definitions, the left/right halves of scale A, the three thirds of K, inverse CI, negations, fractions, powers, discounts/tax, fuel consumption, physics, chemistry, and the units table. Source arithmetic/dimensional inaccuracies were preserved: for example, the gas example's formula gives the printed `1100`, while its instructions give `1110`. In example 59, original feet coexist with sq. inches. The translation does not silently correct the author.

The first automatic result **required editorial corrections in 44 of 213 blocks**. This is not claimed as automatic acceptance without intervention:

- 30 blocks: original ASCII function names were restored where the model had translated them as `квадрат(...)` / `квадратный корень(...)` / `кубический корень(...)` (square / square root / cube root).
- 10 blocks: `indicator` was aligned with the accepted “бегунок” (cursor). Extraction had created no anchors in these early blocks, and the previous prompt supplied only senses with anchors in the current package.
- 3 blocks: “десятичная точка” (decimal point) was standardized. 1 block: an extra sentence unsupported by the source was removed. 1 block: a grammatical case was corrected. The categories overlap in part.

The causes of two systematic defects were fixed in code: projection 3 protects the named ASCII functions, and workflow 3 supplies the full relevant glossary even without anchors. Earlier workflows 1/2 retain their prompts/checkpoints. Separate real checks: five paragraphs with formulas — **20,450 s**, with markers/functions preserved. Two previously problematic paragraphs with unanchored `indicator` — **17,459 s**, with the model using “бегунок”. These are two additional calls, separate from the full run's six calls. A full automatic workflow/projection 3 run after these fixes **was not repeated**.

Corrections were submitted through public `draft save` as **r2**, followed by `draft render --revision 2 --wait`: local render `07be2cfe31ef42f2`, without inference. When removing the extra phrase, the editor initially rejected an empty source span. The phrase was redistributed over original line breaks without removing markers. Earlier r1 and its EPUB were retained. The source, all senses, and 165 source occurrences are unchanged. One affected translation anchor is marked manual. Correction log: `editorial-corrections.json`.

Finished file: `outputs/epub-whole-book-2026-11-04/stanley-ru-reviewed.epub`, SHA-256 **`caa53698e42fb719e505064280e515d02f4618d2ed57a978685583c49e10a11d`**. EPUBCheck 5.4.0 for r1 and r2: **0 errors / 0 warnings**. Independent r2 audit (`--projection-version 2`) confirmed the tree/non-translatable attributes, 66 immutable resources, 134 local links, and original notice text, with no findings.

## Reading, interfaces, and limitations

The r2 ZIP book itself was opened in EPUB.js: cover, navigation from the spine, beginning (screen 7), middle/`cube_root` (60–61), ending/units (88), and NCX navigation to the original license (92). All **61 main-XHTML images** loaded, none broken, plus a separately checked cover. The source book has only one license entry in NCX. It was preserved, and no new author chapters were invented. Screen numbers refer to the specific width/height.

The narrow check used a 390 px reader column and an actual book area of **370×555 px**: line wrapping was readable, page navigation worked, maximum displayed image width was **340 px**, and no images were broken. This does not establish a complete mobile application UI. For EPUB 3, four TOC entries, a table, SVG, MathML, code, and footnote navigation/back were additionally checked. Screenshots: `reader-start.jpg`, `reader-middle.jpg`, `reader-formulas.jpg`, `reader-end.jpg`, `reader-ncx-license.jpg`, `reader-narrow.jpg`, `reader-synthetic-*.jpg`.

Real Streamlit showed r2, original fragments, the glossary, two retained notices, and download. The button-downloaded file matched SHA-256. The browser-tool download step took about 30 minutes: the screenshot was saved at 18:00:10 UTC, and the file appeared in Downloads at 18:30:11 UTC. Direct GET of the same Streamlit's standard media endpoint returned all 3 654 693 bytes with the correct SHA in **0,075 s**. Clicking again without waiting for a download event returned in **0,420 s**, but no new file appeared in Downloads. This points to the QA browser stage, but the exact cause is unestablished and total download time is not accepted. These measurements are separate from the worker's 16:29. `ui-ready.jpg`, `download-qa.json`, `http-download-qa.json`, and `download-retry-qa.json` record the result. Local rebuilding of an existing EPUB was also fixed: Build EPUB remains available, and both clients prefer the latest available export of the selected revision. An old EPUB that fails to open can be rebuilt without translation. A missing Russian label for EPUB render state was added.

**199 targeted offline tests passed**: EPUB/XML safety and namespaces, older projections, plain math, late glossary, core/worker/recovery, CLI/UI, and local rebuilding without repeat inference. Ruff check/format and diff check pass. The expensive model boundary is substituted in tests. The eight real calls are described separately. The project and QA use separate XDG folders. No unfinished QA jobs remain.

Significant limitations remain: the automatic glossary does not guarantee exhaustive occurrences/anchors, so unanchored phrases do not participate in targeted correction. Grammar beyond the corrected phrase, the full class of plain-text mathematical notation, long modern textbooks, and specific hardware readers are not accepted. Raster-image/cover labels remain original. The first proofread book is readable, but full automatic output quality under the current rules requires a separate check. PDF and narration were not performed.

Primary contracts: [OPF 2.0.1 / NCX](https://idpf.org/epub/20/spec/OPF_2.0.1_draft.htm#Section2.4.1), [EPUB 3.3](https://www.w3.org/TR/epub-33/), and the pinned EPUB.js source code. PDF and narration are not checked at this stage.
