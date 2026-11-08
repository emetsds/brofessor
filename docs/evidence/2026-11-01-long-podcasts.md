# Long podcasts: duration and recovery

Historical report. Current requirements and boundaries are in the [specification](../specification.md), and decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state at the time of the experiment.

Checked 01–02.11.2026 on Apple M4, 32 GiB. The matrix of four 25/60-minute RU/EN episodes on one book was completed. This is the second M2 item. This report does not declare full R06 acceptance, quality of all voices, or series complete.

## Implementation

For 20–60 minutes, a single episode outline is saved (`outline.json`), then sections of about five minutes are written. Their purposes and source references are specified in advance. Checks cover section count, unique headings, both hosts, language, valid IDs, and each section's length with 15% tolerance. One substantive correction fixes an overly short/long section. An unacceptable correction does not become a checkpoint and can be retried on resume.

Initial long-script estimates were 125 words/min for RU and 100 for EN. The English measurements below came from initial drafts estimated at 125 and subsequent substantive editing. The full run showed about 90–100 words/min, so the initial estimate was revised. The new 100 estimate was verified by contract tests; a separate full neural run with it was not repeated. It does not guarantee duration: models, voices, and content differ. Russian numbers and foreign names are requested in spoken form. Long turns are split without losing words to 300 characters RU / 400 EN, preferring sentence boundaries. A word becomes the boundary if a whole sentence does not fit. Short previews retain their earlier prompts/checkpoints.

After synthesis, the shared calculation returns measured duration, deviation from the request, word count, measured speaking rate, and an editing estimate. Full episodes must satisfy both 10% tolerance and the 20–60-minute range. CLI receives these fields in metadata. The UI shows actual and target duration and, on mismatch, a word-count suggestion. Sidecar `podcast.audio.json` contains the same final metadata. The coverage table is collapsed so it does not push the player and finished file away.

## Source and verification method

Complete [Mary Shelley — Frankenstein](https://www.gutenberg.org/ebooks/84) EPUB, with the same SHA-256 and original 90 fragments as the [whole-book check](2026-11-01-whole-book.md). 89 fragments are readable, one empty fragment is excluded. The 25-minute focus covers six control plot questions. The hour-long focus is a sequential examination of the entire story, responsibility, loneliness, and character decisions.

The official stable subscription Codex CLI writes text. Installed local models create audio with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. No paid API or automatic provider switch. The exact server-side text-model revision was not recorded. Bit-for-bit reproducibility is not claimed.

To speed up test setup, only previously accepted reading results with matching full fingerprints were copied. The new broad hour-long focus received its own reading, and the English version reused the accepted notes for that focus. This was experiment preparation, not an implemented general cross-job cache.

Russian and English runs used separate test projects, each with one OS-locked worker. Russian used CPU, English used Metal, and they ran in parallel. Times below apply to these particular conditions, not a model comparison under equal conditions.

## Why a different Russian TTS was selected

Short technical smoke tests did not expose defects in the long Qwen profile. In the real run, Qwen3 0.6B stopped at turn 38 after reaching the generation limit. Some accepted PCM segments were also defective: for example, 33 words took 83,84 s, and spot ASR checks showed repeated syllables and omissions. Lowering temperature to 0,1 did not help that turn.

Qwen3 1.7B passed three short problematic turns, but omissions and excessive pauses also appeared in a longer Russian run, which was stopped. These results apply to the pinned 4-bit presets, Ryan/Vivian voices, and current runtime, not all possible upstream configurations. A note was added to the catalogue and README. Failed results were not presented as usable long episodes.

Control Russian turns were regenerated with the already integrated Silero and ESpeech. English was checked separately:

| Profile | Audio, s | Render, s | Observation |
|---|---:|---:|---|
| Silero CIS Base, RU | 45,79 | 2,20 | Meaning retained in spot ASR checking; no looping found |
| ESpeech RL-V2, RU | 54,47 | 256,53 | Meaning retained in spot checking; this profile is substantially slower than real time |
| Qwen3 1.7B, EN | 43,85 | 19,92 | Two turns match the text semantically, with no omissions detected |

These are short runs including engine loading, not a general benchmark or pronunciation-quality assessment. Silero CIS Base with `ru_roman` / `ru_zhadyra` was selected for the long Russian test, and Qwen3 1.7B with Ryan / Vivian for English. Exact weight revisions and settings are saved in each render job. The choice was explicit. The runtime introduces no fallback.

## Finished results

Four final variants completed. Metadata contains `duration_matches: true`, word count, and measured speaking rate.

| Language / model | Target | Actual duration | Words / turns | Final assembly, s |
|---|---:|---:|---:|---:|
| RU / Silero CIS Base | 25 min | 23:49 (1429,3375 s) | 3105 / 112 | 20,909 |
| RU / Silero CIS Base | 60 min | 57:52 (3471,5 s) | 7301 / 270 | 47,789 |
| EN / Qwen3 1.7B | 25 min | 24:50 (1490,05 s) | 2499 / 54 | 2,510, all audio from cache |
| EN / Qwen3 1.7B | 60 min | 59:17 (3557 s) | 5338 / 117 | 21,738, 114 of 117 segments from cache |

These results satisfy both tolerance and the overall range. FFmpeg completely decodes all four MP3 files without errors. Final English assemblies mostly use finished segments, so their time cannot be presented as full neural-synthesis speed. Initial full hour-long English narration took 1879,043 s. The full 25-minute version after local recovery took 483,046 s with 18 cached segments, excluding the preceding failed attempt. Weight loading and warmup are included.

### Substantive editing of English episodes

The first English render stopped at turn 19/62. Splitting only that turn into three retained every word, role, and reference. The new revision reused the first 18 finished segments. This produced complete audio, but its 29:06 (1746,07 s) missed the 25-minute target.

From measured speaking rate, the service suggested about 2501 words instead of 2911. Revision 3 removed ten redundant turns: repeated summaries and verification details already explained by neighboring turns. Transition coherence, retention of all six answers, and original references were checked. 2499 words remained. The saved script was changed; audio speed was not, and PCM was not manually trimmed. All 54 remaining segments were reused, and actual duration of the new assembly was 24:50. Earlier revisions and render jobs remain.

The first hour-long English variant had 7108 words, 155 turns, and 79:24 (4764,18 s). It explicitly failed its target. Measured speaking rate suggested 5371 words. Editing removed 44 repeated interpretations and secondary details while preserving 5338 words, all 12 sections, chronology, and significant caveats. Transition checks restored the explanation of Victor's warning, context of his studies, an instance of the Creature's restraint, and interpretation of the wedding-night threat.

The five slowest English turns were additionally checked with ASR. One omitted the phrase about Clerval caring for Victor; another had excessive pauses and a questionable ending. Both were split without changing words and narrated again. Revision 2 had 116 finished segments, 109 from cache, and 59:14 in 36,082 s. An additional revision corrected the `their / father` boundary by replacing it with whole sentences. Final revision 3 has 117 segments, 114 from cache, and 59:17 in 21,738 s. Repeated ASR checking covered the new parts. Following this observation, automatic splitting now prefers a sentence even after a short introductory phrase.

Manual review of the hour-long scripts checked Elizabeth's adoption history, circumstances of Victor's mother's death, Justine's coerced false confession, the alibi specifically at the time Clerval's body was found, and the Creature's final intention without presenting it as an observed death. The 12-part plan covers the story sequentially. Interpretations of relationships and responsibility are labeled separately from plot facts. The animation method is not replaced with a cinematic lightning scene.

## Audio checks and boundaries

Spot checking uses [Whisper Base MLX](https://huggingface.co/mlx-community/whisper-base-mlx/tree/1e3e249fb8d01c655324bd6841b1deadffd6d04c), revision `1e3e249fb8d01c655324bd6841b1deadffd6d04c`, with the native [OpenAI Whisper Base tokenizer/config](https://huggingface.co/openai/whisper-base/tree/e37978b90ca9030d5170a5c07aadb050351a65bb). This is auxiliary CPU QA through installed MLX-Audio 0.6.3, without new application dependencies or an ASR service. The old NPZ's service `alignment_heads` is unused. The tokenizer was loaded explicitly and then operates without network access.

The beginning, middle, and end of each voice's turns were taken from every final episode: 24 excerpts. Slow and corrected English parts were additionally checked. No obvious looping was found in the final sample. Differences in recognizing individual names, words, and endings remain, so verbatim narration accuracy is not declared established. ASR itself makes errors, particularly on names and Russian endings. It does not replace listening, evaluation of timbre/stress placement, or measurement of the percentage of all defective turns. The four episodes were not listened to in full. Silero CIS Base does not place stress automatically: names and ambiguous words may need manual `+` editing.

## Artifacts and application checks

Local artifacts are in `outputs/long-podcasts/` (ignored by Git): `final-matrix.json` with exact model snapshots, `final-asr-checks.json`, original outlines, scripts, logs, and intermediate failed runs. Relative paths to final MP3 files:

| Variant | Script / revision | Audio |
|---|---|---|
| RU 25 | `8ed7fd510034451d` / 1 | `ru-workspace/jobs/e6612347d67d4ac8/podcast.mp3` |
| RU 60 | `82bff4f1bc2845cc` / 1 | `ru-workspace/jobs/da3bad585a47454e/podcast.mp3` |
| EN 25 | `b4895a717c1b4a01` / 3 | `en-workspace/jobs/7f68d9403a474e3e/podcast.mp3` |
| EN 60 | `e475efa541784cde` / 3 | `en-workspace/jobs/4f4796c343ed401f/podcast.mp3` |

Environment: Python 3.12.13, MLX-Audio 0.6.3, MLX 0.32.4, Torch 2.15.0, Streamlit 1.66.1, SoundFile 0.14.0, imageio-ffmpeg 0.7.0. **257 offline tests**, Ruff lint/format, and `git diff --check` pass. Checks cover outline saving, retrying only failed editorial attempts, section limits, word preservation during splitting, matching sidecar/metadata, duration and both UI/CLI locales, and audio reuse after deleting/reordering turns. A real browser showed the warning for 29:06 / target 25:00 and finished players 24:50 / 25:00 and 59:17 / 60:00. Screenshots: `ui-duration-warning.jpg`, `ui-final-ru.jpg`, `ui-final-en.jpg`.

Series, other books, and full subjective quality acceptance remained subsequent checks. These four cases do not establish universal TTS robustness.

## Content review of earlier episodes

02.11.2026. Existing materials were reviewed for content before later cancellation of personal M4. No new text jobs or dependencies. The first pass produced two script revisions and two renders, synthesizing one turn. The continuation below describes another two revisions, six new audio segments, and protection against the discovered defect. **The user did not accept this RU/Silero pilot because of speech and stress-placement quality. Full listening and acceptance of the English profile were unfinished. Personal M4 had not been completed at the time of the experiment and was later cancelled under D027.**

### Review scope

The saved complete Frankenstein EPUB from the [book check](2026-11-01-whole-book.md), four [long episodes](2026-11-01-long-podcasts.md), the [Russian series](2026-11-02-podcast-series.md), and short synthetic material from [runner acceptance](2026-11-02-provider-acceptance.md) were used. The book source has SHA-256 `bf04d57cf243314ab770df6fcea6a9cfb1e5a281426453e23c128c5a9c3eb662`; the short source is `tests/fixtures/chapter.md`.

Two 25-minute-target scripts and three series scripts were read in full. Both hour-long scripts were finished in the continuation, with their events and caveats spot-checked against the original. This is not an independent check of every claim in all seven episodes. For 28 control claims, original fragments, locators, affected scripts, and manual-comparison outcomes are recorded in `outputs/content-acceptance/content-checks.json`. Its line count is not an overall quality metric.

References below use fragment numbers of saved source `bf04d57cf243314ab770`. Fragment numbers differ from chapter numbers in the book text.

| Distinction checked | Original fragments | Comparison result |
|---|---|---|
| First letter's recipient and place of writing | 4–5 | Margaret Saville is the sister. St Petersburg is the letter's location, Archangel the planned next journey. |
| Elizabeth's history and the mother's death | 13, 17 | The account of Elizabeth joining the family in this edition is retained. The mother contracts illness while caring for her. The loss is not called the experiment's sole established cause. |
| Animation and first encounter | 21, 23 | About eight feet tall, a November night at around one. Lightning is not added as the animation method. An outstretched hand is not presented as a proven attack. |
| Henry's care | 24–25 | Grammar and an incomplete reference were corrected: the winter in the sickroom is described in fragment 24, the response about repayment in fragment 25. |
| Justine's confession | 34–35 | The false confession and confessor's threats are retained. Victor's moral self-blame is not presented as murder by his own hand. |
| The Creature's learning | 48, 51 | The three found books, journal from clothing, and Felix reading Volney are distinguished. Partial understanding of Werther is not turned into full adoption of his views. |
| Conversation with De Lacey | 53 | The old man's sympathy, reactions of those returning, and the Creature's restraint are conveyed separately. There is no claim that the old man refused to listen. |
| William's murder and framing Justine | 56 | The Creature's confession is retained. An explanation through rejection does not replace responsibility for actions. |
| Henry's independent goals | 62 | The Indian project is linked to colonization and trade. An intention is not presented as accomplished success. |
| Companion and threat | 65–66 | The Companion's future will and character remain assumptions. The threat names the wedding night, while Victor infers the specific victim. |
| Clerval and the alibi | 69, 71 | Discovery of the body and testimony about the boat do not substitute for witnessing the murder. The alibi concerns the time the body was found. |
| Wedding and subsequent deaths | 74, 77–78 | The secret is promised after the wedding. Victor sees Elizabeth's body and the Creature's escape, not the killing itself. His father's death and later imprisonment are not merged into one event. |
| Transmission of the narrative | 83 | Victor's participation in editing Walton's notes is recorded, without treating it as independent evidence of lying. |
| Return and ending | 84–85, 87 | Agreement on the seventh of September is separated from the passage opening on the eleventh. The Creature's self-immolation remains a promise. Only departure on a raft is observed. |

These comparisons found no new substitutions of plot facts. The discovered incomplete reference was corrected. That conclusion applies to the selected claims and revisions, not an arbitrary book or runner.

### Corrections and editing scope

**First series episode:** script `8f1b7edd58ab4fc4`, revision 2 → 3. In turn 60, “Генри остаётся его единственным сиделкой” (an ungrammatical “Henry remains his only nurse”) was replaced with “за ним ухаживает только Генри” (“only Henry cares for him”). Turn 61 received both required references, 24 and 25. Other turns' text was retained. New render `0397f144453f43e4` reused 96 of 97 segments. Changing a reference alone did not trigger resynthesis. Duration was 1223,7625 s, about 20:24; the previous file was 1224,55 s.

**Russian episode with a 25-minute target:** script `8ed7fd510034451d`, revision 1 → 2. Original turns 2 and 16–18 were removed: an introduction without new content and repetition of an answer already given about the letter. The transition from that answer to the books question remains coherent, with all six answers and significant caveats retained. 95 words were removed, leaving 3010 words and 108 turns. New render `ac91c97c4b794e29` used all 108 segments from cache. Duration fell by 46,625 s, from 23:49 to 23:03, remaining within tolerance for the 25-minute target. Rate, pauses, and audio waveform were not stretched to meet the target.

Edits were saved through `service.edit_draft` with an expected revision. Renders were created through the shared service with explicit model `silero-cis-base`. Previous revisions, MP3 files, and segments were retained. Original MP3 files for all seven cases were checked against pre-change hashes. New files have their own job IDs. User settings were unchanged. A separate `XDG_CONFIG_HOME`, installed weights, and `HF_HUB_OFFLINE=1` were used.

The runners' short raw/final scripts were compared again. Of Codex's five original turns, four remained verbatim, one was grammatically corrected, and two had been added earlier for substance and duration. Three of Claude's six original turns were rewritten to correct the title, language, and unsupported claim that volunteers had crossed successfully. Ollama's two original long turns had previously been reworked into six, without direct turn-to-turn correspondence. This describes actual editorial work, **not the percentage of erroneous turns**. The “no more than 5%” threshold is not established by these examples.

### Continuation: a long pause in English audio

An acoustic check of all seven files used saved segments: RMS in 20 ms windows, regions below −60 dBFS, turn beginnings/endings, and duration relative to word count. These measures selected suspect passages rather than automatically assessing voice quality.

In EN 25, revision 3, render `7f68d9403a474e3e`, 46-word turn 37 lasted 90,96 s. It contained uninterrupted near-silent regions of 36,56 s, 14,22 s, and 10,62 s. PCM16 amplitude in the longest region was only −41 to 46. The earlier beginning/middle/end sample did not detect the defect. Whisper produced repetitions and an incomplete transcript on this audio. Recognized repetitions over silence are not evidence that TTS itself looped.

The turn was split into three sentences **without changing words, role, or references**. Script `b4895a717c1b4a01` was saved as revision 4, with new render `850e3c316bee480b`. 53 of 56 segments were reused. The new parts last 12,24 / 10,32 / 4,24 s. With two assembly pauses, the whole passage lasts 27,30 s. Maximum near-silent regions are 0,50 / 0,30 / 0,08 s. Repeated local ASR conveys all three sentences, with a different spelling of Clerval's name. Episode duration is 1426,39 s, about 23:46, within the earlier tolerance for a 25-minute target. Time was not compensated with repetitions or audio stretching.

Three wordings were corrected in RU 60: turn 65 incorrectly subordinated the goal to rest and relationships rather than the reverse; turn 76 repeated the “единственным сиделкой” grammatical error; turn 237 omitted a preposition in “помощи, в которой Виктор нуждается” (“the help Victor needs”). Turn 257 received an additional reference to fragment 85: the request for revenge is in fragment 82, while refusal to demand sacrificing country and friends is in fragment 85. Script `82bff4f1bc2845cc`, revision 2, render `65d865115e0c4833`: 267 of 270 segments reused, duration 3471,9375 s, about 57:52. New turns were also checked with local ASR. Differences in Russian endings and names remain subject to listening verification.

Nine other English turns with slow rates or noticeable pauses were additionally checked using installed Whisper Base MLX from the previous experiment. No further confirmed defects were established in this sample. Individual recognition differences were not corrected as proven TTS errors. MLX needed execution outside the restricted sandbox: it initializes Metal even when CPU is selected. Model and processor were loaded from earlier local pinned directories, with `HF_HUB_OFFLINE=1`, no new downloads, and no cloud transmission of audio.

#### Application protection and checks

Shared `media._synthesize` now rejects a **new** segment with ten uninterrupted seconds of RMS below −60 dBFS before writing WAV/checkpoint. The error names the turn and suggests splitting or editing it. Audio is neither truncated nor automatically narrated again. This narrowly protects against an obvious stall. It is not a user-approved comfortable-pause threshold or a semantic check of spoken words. Historical caches and finished jobs are not invalidated. A corrected revision is retained for the known old defect.

A regression test reproduces speech with a long interval of weak nonzero noise through the real `_synthesize` check: the failed segment is not accepted, the previous artifact stays intact, and a corrected retry uses the completed first segment. Temporarily raising the threshold to a thousand seconds **only in a separate process's memory** makes this test fail. Disk code was not substituted.

On real saved WAV files, the check rejected the original EN 25 turn and accepted nine other suspect EN 60 turns, preserving frame count and sample rate. This is not a new model call. Every earlier MP3 was checked by hash, and both new ones were fully decoded. English script word preservation and saved segment keys were checked separately. Both final matrices, scripts, and listening materials were updated.

Local evidence: `acoustic-scan.json`, `risk-asr.json`, `risk-repairs.json`, `repaired-asr.json`, `post-repair-acoustic.json`, `guard-replay.json`, `stall-mutation.json`. The corrected English excerpt is separately available as `clips/en-25-turn37-fixed.mp3`.

### Current results

| Variant | Revision | Render job | Duration |
|---|---:|---|---:|
| RU, 25-minute target | 2 | `ac91c97c4b794e29` | 23:03 |
| RU, 60-minute target | 2 | `65d865115e0c4833` | 57:52 |
| EN, 25-minute target | 4 | `850e3c316bee480b` | 23:46 |
| EN, 60-minute target | 3 | `4f4796c343ed401f` | 59:17 |
| Series, episode 1 | 3 | `0397f144453f43e4` | 20:24 |
| Series, episode 2 | 1 | `71ba4c1fd8114ac1` | 20:10 |
| Series, episode 3 | 2 | `cdf5854a84294dcd` | 20:42 |

All seven pass the earlier duration check. Existing files were checked for complete FFmpeg decoding, EPUB original hash, each turn's match to saved audio-segment text, voice/language, segment SHA-256 integrity, and summed durations with assembly pauses. New RU 25 and the first series episode were checked after rebuilding. This checks provenance and technical integrity, **not absence of omissions or pronunciation errors within synthesized speech**.

After the shared-renderer change, **356 offline tests**, Ruff check/format, and `git diff --check` pass. Tests do not call real models. Local-render and ASR results are described separately above. Application dependencies were unchanged. No tests for specific literary wordings were added.

### Materials provided for listening

`outputs/content-acceptance/listening-guide.md` contains players for two pilots and links to seven complete MP3 files with their corresponding scripts. The RU/Silero pilot lasts 1:45, EN/Qwen3 1.7B 2:51. Each combines complete neighboring turns from the beginning, middle, and end of the hour-long episode, with semantic jumps between selected passages marked. Three individual excerpts were saved for each of the seven episodes. `listening-manifest.json` contains exact original-MP3 intervals, turn numbers, expected text, revisions, and hashes. These are derived local QA files, not new neural-synthesis results. They are not in Git.

Feedback on the Russian pilot was received: “Русский звучит очень плохо, ударения почти везде неверные” (“The Russian sounds very bad; stress placement is wrong almost everywhere”). The pilot uses `silero-cis-base`, `ru_roman` / `ru_zhadyra`, and this profile did not pass user listening acceptance. The feedback concerns the presented sample and does not establish a measured percentage of defective turns. The technical checks and ASR above do not refute this assessment. The next speech step was to select and verify a short Russian sample with acceptable pronunciation before another long render. Isolated manual corrections were not declared a solution to the overall problem.

Feedback on the English pilot had not yet been received. Full listening to about 3 hours 45 minutes of material was unfinished. Findings need to be tied to an exact revision, time, and turn, then the affected text or segment corrected and the appropriate check repeated. Until then, full listening acceptance remains unfinished.
