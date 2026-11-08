# First EPUB translation trial with formatting preservation

Historical report. Current requirements and boundaries are in the [specification](../specification.md); decisions and cancellations are in the [Decision log](../decision-log.md). References to later stages describe the state at the time of the experiment.

04.11.2026. First technical comparison of approaches; the choice is recorded in [D015](../decision-log.md#d015-04112026--epub-assembled-locally-from-protected-blocks). This is a technical trial on a short chapter and a source-based assessment of a PDF candidate. This experiment did not implement whole-book translation or a user-facing CLI/UI job. Speech checking was postponed until a separate user signal.

**Later continuation on 04.11:** [terminology and the early EPUB path through worker/CLI/UI were implemented](2026-11-04-book-terminology.md). Results of the first technical trial are retained below; its cache is not used as the product's revision/resume mechanism.

## Material and conditions

An original synthetic chapter, **Reliable sensor ingestion**, with sources in `tests/fixtures/translation/`. All text, CSS, and SVG were written for brofessor and distributed under the repository's MIT license. The fixture contains no existing books, third-party illustrations, external fonts, or user materials. The source is packaged as reflowable EPUB 3; the spine defines reading order.

The projection has 43 translatable blocks, about 620 words including headings/navigation and excluding protected code/formulas. It includes recurring terms, two senses of `log` (“журнал” / “бревно”, journal / timber) and `head` (“напор” / “руководитель”, pressure head / leader), negations, numbers and units, emphasis, a table, a footnote with a return link, an SVG illustration, MathML, and code. An eight-entry glossary was written manually and is identical for both methods. This is **not automatic terminology extraction**.

Environment: Python 3.12.13, Pydantic 2.14.2, official stable `/Users/demets/.local/bin/codex` **0.162.1**. The runner reported **`gpt-6.1-sol`, reasoning effort `none`** for both calls. Initial calls used the CLI default; the model actually selected was recorded from the runner header in `calls.json`. The final probe requires explicit `--model` for subsequent reproducible comparisons. Standard subscription authorization was used; no API keys or paid API were connected. Only the synthetic chapter was transmitted. User settings were unchanged.

## Comparison

| Method | Model calls | Time, s | Prompt characters / UTF-8 bytes | Schema characters | JSON-response characters |
|---|---:|---:|---:|---:|---:|
| Whole-XHTML translation | 1 | 45.238 | 7 492 / 7 568 | 1 048 | 6 614 |
| Protected text blocks | 1 | 53.840 | 12 345 / 12 504 | 498 | 7 072 |

Time includes standard authorization checking and runner execution. These are two observations on one short material, not a statistical speed comparison. Sizes concern the application prompt/schema before the executor's internal transport instructions. Tokens and cost were not measured and are not inferred from character counts. Before these calls, one OS-sandbox launch failed (0.671 s); it is recorded separately as a launch error, not a translation.

The first method returns complete XHTML from the model. The second uses `epub_translation.py` to extract text blocks and accessible text attributes, replacing inline markup with markers. The model returns only text with existing IDs. Code checks exact coverage, marker order, nonemptiness of originally nonempty spans, and retention of numerical values, including signs and permissible decimal-separator changes. Tags, link attributes, paths, styles, and resources are restored from the source snapshot. Foreign markup in the response is escaped as text. New-file creation is atomic; the original cannot be chosen as output, including through a symlink/hardlink.

**The decision for further implementation is protected blocks with local assembly.** Here they require approximately 65% more input text and 19% more time. The experiment did not demonstrate better translation quality: both methods handled the short example. The choice rests on verifiable local structure guarantees, separately addressable blocks for later corrections, and no new framework/dependencies. Whole XHTML remains a control method in the probe; there is no production fallback between the two.

## What was actually checked

For both results, programmatic comparisons cover the resource set, XHTML tree and non-translatable attributes, original CSS/SVG, code content, and MathML. Local links and anchors resolve. Spine order is preserved; the new book receives a separate identifier, language, and `dc:source` containing the original identifier. The table, caption, footnote, accessible `alt`/`title`/`aria-label`, and navigation were translated. The result retains a source-XML-position map with the original SHA-256; these are internal projection locators, not new HTML anchors.

**EPUBCheck 5.4.0**, run through OpenJDK 24.0.2, checked the source and both translations: **0 errors, 0 warnings**. Its actual message states validation against EPUB 3.4 rules. This checks format, not semantic accuracy. EPUBCheck was downloaded from the [official release](https://github.com/w3c/epubcheck/releases/tag/v5.4.0), has an [MIT license](https://www.w3.org/publishing/epubcheck/), is used only for QA, and was not added as an application dependency. ZIP SHA-256: `33350c61038e71dfb3d45a76aed04bf5481e6d5500cb780f6e98db8bbd15a28c`.

Both translations were compared in full with source texts by the agent; no separate external editor participated. This material showed no omitted sentences, changed numbers, lost key negations, or confusion among the tested term senses. Both versions preserve the ban on acknowledgment before durable commit, the possibility of losing an unacknowledged record, the limitation of results to a particular setup, and the exclusion of storage-medium destruction. The baseline retained international `V/s/m/ms` and decimal points; the block method localized them to `В/с/м/мс` and commas. These are permissible notations, not evidence of different semantic quality. Phrases such as “действительная контрольная точка” (“valid checkpoint”) could be improved editorially; the automatic contract does not assess them.

The full source and both translations were viewed in a browser at 900 px width; the block result was additionally checked at 530 and 390 px. Cyrillic, emphasis, table rows, illustration, formula, and original code are visible. No overlaps/truncation were found; there is no horizontal overflow at 390 px. Navigation → section, table link, footnote, and return were checked by clicking. Screenshots are beside the results. Browser XHTML viewing **does not replace checking the EPUB in its target reader**, which remains part of later whole-book acceptance.

126 offline checks of EPUB/import/executor boundaries passed. They cover exact reconstruction, snapshot/original preservation, text and accessible attributes, nested mixed content, rejection of lost/duplicate/fabricated IDs, numbers and markers, preservation of the previous file after a bad answer, and explicit refusal of unsupported input. These are separate evidence from the two real model calls. Audio and other product workflows were not regenerated.

## Assessing BabelDOC for PDF

The sources of stable **BabelDOC 0.6.4** were examined, not an installed integration path. [Release](https://github.com/funstory-ai/BabelDOC/releases/tag/v0.6.4), [dependencies and AGPL-3.0 license](https://github.com/funstory-ai/BabelDOC/blob/v0.6.4/pyproject.toml). Source ZIP SHA-256: `34febc0a98fefe5b911798878eba05e645d940b16bc044f51558b95c8fed2e4a`.

[`TranslationConfig`](https://github.com/funstory-ai/BabelDOC/blob/v0.6.4/babeldoc/format/pdf/translation_config.py) accepts a `BaseTranslator` and separate terminology translator. [`BaseTranslator`](https://github.com/funstory-ai/BabelDOC/blob/v0.6.4/babeldoc/translator/translator.py) has `do_translate` and `do_llm_translate` extension points. Therefore, **based on interface analysis**, a bridge to `executors.generate` with a text JSON wrapper is possible without OpenAI API billing: the existing CLI still owns official subscription authorization, while Ollama uses its selected server. Compatibility of such a bridge with a real PDF pass was not checked. The `do_llm_translate(None)` probe, cache identity, and bounded/concurrent calls must be considered; no ready adapter is claimed.

The candidate has its own layout model, fonts, caches, and many dependencies. In the examined configuration, failing to supply a layout model causes a download through `DocLayoutModel.load_available`. Resource metadata contains network URLs. The card for the [DocLayout ONNX conversion used](https://huggingface.co/wybxc/DocLayout-YOLO-DocStructBench-onnx) states Apache-2.0; this is not a complete license audit of the entire set. Fonts and other resources from [BabelDOC-Assets](https://github.com/funstory-ai/BabelDOC-Assets) were not separately accepted or downloaded. Their licenses cannot be inferred from the main code's license. The [official README](https://github.com/funstory-ai/BabelDOC/tree/v0.6.4#readme) marks table translation experimental.

**BabelDOC remains a candidate and is not integrated into the MIT application.** Only sources were downloaded for reading. Its dependencies were not installed, layout inference was not run, weights/fonts were not downloaded, PDFs were not translated, and Cyrillic/overflow were not checked. This assesses feasibility and boundaries of the next PDF trial, not positive PDF acceptance.

## Artifacts and reproduction

Local results: `outputs/epub-translation-2026-11-04/` (excluded from Git):

- `original.epub`, `whole-xhtml.epub`, `protected-blocks.epub`.
- `calls.json`, exact `*-request.json`, JSON responses, `alignment.json`, `*-structure.json`.
- `original-900.jpg`, `whole-xhtml-900.jpg`, `protected-900.jpg`, `protected-390.jpg`, `protected-default.jpg`.
- `babeldoc-source/` — the pinned release files examined, for local checking only.

Original SHA-256: `e757b7f39db454309d3dc24d73a2520dd17da80c594f62af048df52678c0fdb8`. Binary EPUBs and new translations are not included in the public repository. A new clone contains the synthetic fixture, experimental core, probe, and this report. For a new comparison, select a separate output directory and explicitly pin the model:

```sh
BROFESSOR_CODEX_BIN=/path/to/stable/codex uv run --no-sync python tools/probe_epub_translation.py \
  --provider codex --model gpt-6.1-sol --output outputs/epub-translation-next
uv run --no-sync pytest -q tests/test_epub_translation.py tests/test_sources.py tests/test_executors.py
```

Packaging policy is based on [EPUB 3.3](https://www.w3.org/TR/epub-33/): the package, spine, XHTML, navigation, and resources are preserved separately. No new Python dependencies were added. The fixture embeds no fonts; the browser used system serif/monospace.

## Prototype boundaries

EPUB 2/NCX, fixed layout, multiple packages, encryption/obfuscation/signatures, scripted content, media overlays, and XML with DTD/entities are explicitly rejected. Only declared XHTML documents are read. Code, MathML, and illustrations are preserved; text inside images is not translated. Inline markers cannot yet be reordered: complex grammar that reorders nested emphasis needs a separate decision. Number validation is conservative and does not check units, negations, or meaning.

There is not yet a working automatic glossary, selective updates by term sense, saved user translation revisions, bounded whole-book batches, or a shared-queue job. The probe cache stores comparison responses and is not presented as a product checkpoint/revision mechanism. Claude/Ollama translation support was checked only at the existing executor level; no new real translations were performed with them. Subsequent criteria remain in P1 of the shared plan.
