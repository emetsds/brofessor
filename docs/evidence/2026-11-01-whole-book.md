# Whole book: reading and fact checking

Historical report. Current requirements and boundaries are in the [specification](../specification.md); decisions and cancellations are in the [Decision log](../decision-log.md). References to later stages describe the state at the time of the experiment.

Checked 01.11.2026 on the target Mac. This is the first M2 item: a complete source, reading coverage, and references. Long narration and a series were not checked here.

## Material and execution

The complete English book by Mary Shelley, *Frankenstein; or, The Modern Prometheus*, was used: [Project Gutenberg No. 84](https://www.gutenberg.org/ebooks/84), [EPUB without images](https://www.gutenberg.org/ebooks/84.epub.noimages).

- File: 294 175 bytes, SHA-256 `bf04d57cf243314ab770df6fcea6a9cfb1e5a281426453e23c128c5a9c3eb662`.
- Import: 437 333 characters, 90 fragments, of which 89 were readable and one empty. The preface and EPUB auxiliary material were also processed; the book's ending was not truncated.
- `ask` job: `52b4f92c68f1476e`, a Russian query over an English source, with six questions about details from the beginning, middle, and ending. The entire source was selected.
- Runner: the configured official stable Codex CLI with a ChatGPT subscription, without API billing. Model selection was left to the CLI. The exact server revision was not recorded, and bit-for-bit reproducibility is not claimed.

The questions concerned the recipient and location of Walton's first letter, the three books read, the conversation with De Lacey, Clerval's murder and Victor's alibi, the decision to turn the ship around, and the final scene with the creature.

## Measurements

| Metric | Result |
|---|---|
| Job status | `succeeded` |
| Reading coverage | 89/89 readable, 1 empty excluded |
| Reading | 22 model calls, one result for every original ID |
| Final answer | 1 model call, 10 original IDs in references |
| Total job time | 469.26 s — 7 min 49 s |
| Sum of model-call durations | 468.98 s |
| Largest reading prompt | 24 716 characters, including instructions and the question |
| Final prompt | 53 449 characters |
| Replay with new model calls prohibited | 0.06 s, accepted checkpoints reused |

The batch budget applies to serialized original fragments: 24 thousand characters, with instructions and the user's question added separately. In this run, the notes fit within the final budget of 90 thousand characters without a second reduction. The additional reduction branch was checked offline on a synthetic long source.

## Comparison with the original

The answer was read alongside the original fragments, rather than merely checked for IDs. IDs below are shortened to their suffixes; the full prefix is `bf04d57cf243314ab770:`.

| Check | What the original confirms | ID |
|---|---|---|
| Beginning | A letter to his sister Margaret Saville; the first letter is from Saint Petersburg | `4` |
| Three books | *Paradise Lost*, Plutarch, and *Werther*; the journal was found separately in the clothes | `51` |
| De Lacey | The old man offers help; the family's return and Felix's attack interrupt the conversation | `53` |
| Clerval and the alibi | The Irish coast, a bay about two miles from the harbor; the alibi concerns the time the body was discovered | `67`, `69`, `71`, `72` |
| Walton's decision | Danger from the ice, the crew's demand, and refusal to take the men farther against their will | `84`, `85` |
| Ending | Self-immolation is the creature's intention; the narrator sees it depart on a raft and disappear into the distance | `87` |

All six control questions received supportable answers and references. No Irish town name was invented. The intention in the ending was not presented as an observed event. This is the result of six specific checks on one book, not an accuracy assessment of every possible retelling.

`chapter N` in an EPUB locator denotes the spine import position, not the printed chapter number. In this edition, for example, the original `chapter 22` contains the text `Chapter 15`. The ID, path inside the EPUB, and character range allow the original to be opened without substituting one numbering system for another.

## Interfaces and recovery

CLI `job coverage ID` and real Streamlit on temporary port 18501 showed the same numbers: 89 read, 1 excluded, 10 cited. RU/EN labels and the table of statuses, locators, and references were checked. Reading status is visible before horizontal scrolling.

239 offline tests, Ruff lint, and format pass. Added checks cover reading all fragments in batches and in order, incomplete/duplicate notes, length limits, progress retention on cancellation, checkpoint reuse after worker failure, additional reduction without new IDs, CLI/UI parity, the old coverage format, and pinned render revisions. Failed generation from a short source does not mark it read.

Local results are in ignored `outputs/whole-book/`: the source EPUB, project `workspace/`, answer `answer.md`/`answer.json`, coverage map `coverage.json`, measurements `metrics.json`, and screenshots `coverage-ru.jpg`/`coverage-en.jpg`. They are not in public Git. To open the project, run `brofessor -w outputs/whole-book/workspace ui` from the repository root or connect the folder through the UI.

## Result boundaries

The coverage map shows accepted reading results, not completeness of all facts or semantic proof for every reference. Notes are compressed to the user's focus; further reduction can also lose detail. Important claims must be checked against the original. Reference validation in code ensures only that references belong to the supplied evidence.

20–60-minute RU/EN podcasts, a series, a complete presentation based on this book, and real Claude/Ollama were not checked here. The next M2 item is long narration with duration measurement and substantive script editing.
