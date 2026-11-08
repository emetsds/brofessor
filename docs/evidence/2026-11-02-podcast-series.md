# A podcast series based on a whole book

Historical report. Current requirements and boundaries are in the [specification](../specification.md), and decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state at the time of the experiment.

02.11.2026. A three-episode Russian series based on the complete Frankenstein EPUB was checked on Apple M4, 32 GiB. This is the M2 functional slice, not full R06 speech-quality acceptance.

## What was implemented

`podcast_series` creates an editable plan: a shared topic map with source references, topic-ID allocation to episodes, and a glossary of terms/names. Checks cover unique IDs and titles, valid references, episode count, and assignment of each topic to exactly one episode. This catches allocation errors in an already constructed map. It does not establish completeness of the map itself or detect every repetition under different wording.

`series_episode` creates an ordinary podcast job with the series ID, episode number, and pinned plan revision. It inherits the series' sources, runner, text model, language, and duration. Subsequent plan edits affect new requests. Repeating the same episode and revision returns the earlier job. Its script is edited and narrated in the ordinary way.

Accepted reading notes are saved inside the project in `series-evidence.json`. Episodes use them together with the shared glossary, their own scope, and other episodes' boundaries. There is no separate queue engine, automatic launch of the entire series, or shared cache across unrelated jobs. Preserve the whole project when transferring it. Missing notes cause an explicit error. A substantially new focus requires a new plan with reading for that focus, rather than merely renaming topics in the old map: compressed notes may not retain the details needed.

CLI: `series plan` → `draft show/save` → `series episode ID NUMBER` → ordinary `draft show/save/render`. UI: “Серия подкастов” (“Podcast series”) in the creation form, then the topic map, shared glossary, and individual episode selection in results. Before preparing an episode, the UI requires saving or loading the current plan version. It shows each episode's duration and text runner.

## Real run

The source was the same as in the [whole-book check](2026-11-01-whole-book.md): [Mary Shelley — Frankenstein](https://www.gutenberg.org/ebooks/84), SHA-256 `bf04d57cf243314ab770df6fcea6a9cfb1e5a281426453e23c128c5a9c3eb662`, 89 readable fragments, with one empty fragment excluded.

Text: official stable Codex CLI 0.162.1 with the existing subscription login. The exact server-side text-model revision was not recorded. Narration: installed Silero CIS Base, `ru_roman` / `ru_zhadyra`, CPU, without network access. Model snapshots were saved in render jobs. User settings and the default TTS model were unchanged.

To prepare the experiment, 44 previously accepted reading checkpoints were copied. The core accepts only results with matching fingerprints for the same source, focus, and contract. Planning after restoring reading took 101,5 s with one real `Series` call. This does not measure reading a new book from scratch. The three scripts together made 15 calls: three `Outline` and twelve `Podcast`, without new `ReadingBatch` calls. Script generation took 210,34 / 197,35 / 192,75 s in the sequential worker. This example is not a comparative benchmark.

### Plan and editing

Series `2ab41e4b934b4951`, saved revision 2: 12 topics, 9 glossary entries, three episodes.

| Episode | Assigned topics and boundary |
|---|---|
| 1. Life bestowed and responsibility abandoned | `t1–t4`: Walton's letters, Victor's childhood and research, animation and abandonment of the Creature, William and Justine. Ends with Victor's departure for the Alps |
| 2. The Creature's story: learning, rejection, and the choice of violence | `t5–t8`: the glacier meeting, learning from the De Laceys, books and the failed introduction, confession of crimes, and the demand for a Companion. Ends with Victor accepting the obligation |
| 3. A broken promise and the final pursuit | `t9–t12`: the journey and destruction of the unfinished Companion, Clerval and the alibi, the wedding and Elizabeth's death, the pursuit and ending aboard the ship |

Unnecessary minute estimates were removed from the original plan's titles and briefs. Clerval's care for the sick Victor and Victor's alibi specifically at the time the body was found were clarified. An unnecessary claim that the journey's dates contradicted one another was removed. These edits were saved as a separate revision.

Section boundaries and transitions between episodes were checked. The first does not reveal the Creature's confession in place of Victor's accusation. The second adds the Creature's perspective instead of repeating Justine's trial. The third begins with fulfilling the promise, without retelling the learning story. Walton's framing returns in the ending for the resolution. Significant facts were spot-checked: the mother's illness, Justine's false confession, the books, the planted portrait, the possible Companion's independence as an assumption, the alibi when the body was found, and the Creature's promised but unobserved death. This checks specific boundaries and control facts, not a full independent audit of every claim.

The first script's closing phrase was clarified so its figurative homecoming would not imply an extra journey before the glacier meeting. The third was under 20 minutes after its first render: 19:12 (1152,1625 s). Six turns, 185 words, were added in revision 2 about Clerval's independent Indian enterprise and the differences between him and Victor in using knowledge and human companionship. The passage was checked against original chapter 19, ID `bf04d57cf243314ab770:62`. Other episodes did not retell this material. Speed and waveform were unchanged; 90 earlier segments were reused.

### Finished audio

The target for each episode was 20 minutes. All three final durations meet the 10% tolerance and the overall 20–60-minute range.

| Episode | Duration | Words / turns | Assembly, s | From cache |
|---|---:|---:|---:|---:|
| 1 | 20:25 (1224,55 s) | 2505 / 97 | 15,306 | 0 |
| 2 | 20:10 (1209,6 s) | 2524 / 102 | 14,381 | 0 |
| 3, revision 2 | 20:42 (1241,55 s) | 2619 / 96 | 6,176 | 90 of 96 |

The third assembly time covers six new turns and assembly, not full synthesis. Initial narration of the third episode took about 13,5 s. Render metadata is the source of the table's values.

## Discovered incompatibility and audio checks

Nested typographic quotes in the series title failed Silero validation. Normalization was fixed to replace only known typographic quotes with allowed ASCII equivalents before validation and synthesis by this engine. Original scripts are retained. Digits, Latin letters, and other unsupported characters are still rejected. A contract test checks the text passed to the model and preservation of the original.

FFmpeg decoded all three MP3 files completely without errors. Local Whisper Base MLX checked 19 excerpts: the beginning, middle, and end for both voices, plus the alibi in the third episode. The already installed model and tokenizer from the [long-episode check](2026-11-01-long-podcasts.md) were used, without new application dependencies or weight downloads.

No obvious looping was found in the sample. Some words, names, and endings differ. Without listening, they cannot confidently be attributed to ASR or TTS errors. Full listening, pronunciation accuracy, the percentage of defective turns, and subjective quality are not claimed as verified.

## Interface and storage checks

**275 offline tests**, Ruff lint/format, and `git diff --check` pass. Checks cover topic allocation, unknown references, pre-submission parameters, plan and runner/port pinning, idempotency, preservation of old versions, recovery after failed generation without rereading, no fallback when notes are lost, CLI/UI and both interface languages, protection of unsaved edits, and Silero quote normalization.

A real browser checked the series form, three topic groups, glossary, plan version, episode selection, and repeated episode requests. Russian and English labels were checked in a real browser. Repeating from CLI and UI returned `8f1b7edd58ab4fc4`; the number of jobs then remained four: the plan and three scripts. Audio jobs were created separately later.

Artifacts are outside Git in `outputs/podcast-series/`: `final-matrix.json`, `asr-checks.json`, plans, scripts, logs, and UI screenshots. Original and corrected versions are retained in the `workspace/` project.

| Episode | Script / revision | Final MP3 inside `workspace/` |
|---|---|---|
| 1 | `8f1b7edd58ab4fc4` / 2 | `jobs/31d5e6e165054753/podcast.mp3` |
| 2 | `9b7be675a9724dfa` / 1 | `jobs/71ba4c1fd8114ac1/podcast.mp3` |
| 3 | `cbccce284ad44f4d` / 2 | `jobs/cdf5854a84294dcd/podcast.mp3` |

The real series was checked on one book in Russian. English series, other corpora, full subjective speech acceptance, and real Claude/Ollama remain unverified by this experiment. Earlier individual English episodes do not substitute for that verification.
