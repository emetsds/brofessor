# Long dialogue on Qwen3-TTS Base with ExNihilus voices

Historical report. Current requirements and boundaries are in the [specification](../specification.md). Decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state on the experiment date.

03.11.2026. The control run used three saved podcast revisions based on the complete EPUB of Mary Shelley's Frankenstein. The Russian episode targeting 25 minutes allows comparison of the new voice with the preceding Silero rendering of the same words. The English episode targeting 60 minutes checks the upper request boundary, the second voice pair, and longer turns. A Russian hour-long script of 7 304 words was also selected. It checks long assembly at substantially greater volume without adding to the source text.

| Script | Saved revision | Words | Turns, host / guest | New job |
|---|---|---:|---:|---|
| RU, 25 minutes | `8ed7fd510034451d` r2 | 3 010 | 47 / 61 | `8ac8c32f901c4ba8` |
| RU, 60 minutes | `82bff4f1bc2845cc` r2 | 7 304 | 118 / 152 | `ade9007ab7014d26` |
| EN, 60 minutes | `e475efa541784cde` r3 | 5 338 | 53 / 64 | `de1bd5a172964420` |

Standard service.render and a one-shot worker operated on project copies. Model `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-4bit` pins revision `37e955a1deb861c088ae5f3a67043185f3d1a60c`, and ExNihilus samples pin `5103f8988ee936525fbfb6dc10061bbabd1d584e`. No text models were called in this run. Rendering, recognition, and voice comparison ran locally. Artifacts are in the Git-ignored qwen-long-2026-11-03 folder: `outputs/qwen-long-2026-11-03`.

## Measured results

| Check | Finished audio | Deviation | Words/min | Turns | Last-pass cache | Maximum silence |
|---|---:|---:|---:|---:|---:|---:|
| RU, 25-minute request | 25:32 | +2,11% | 117,92 | 108 | 0/108 | 0,80 s |
| RU, 60-minute request | 63:44 | +6,22% | 114,60 | 270 | 0/270 | 1,12 s |
| EN, 60-minute request | 35:13 | −41,30% | 151,56 | 117 | 75/117 | 0,88 s |

The Russian 25-minute check met tolerance. Both hour-long requests exposed a script-volume problem. The Russian file exceeded the upper 60-minute boundary, while the English file was substantially shorter than requested. Based on these measurements, new jobs pin estimates of 115 words/min RU and 150 EN. Volume targets the middle of the acceptable duration interval, specifically 21 minutes for a 20-minute request and 57 for a 60-minute request. Historical jobs retain their earlier budgets and checkpoints. New targets were checked at the boundaries and on resubmission. Separate new scripts using them were neither generated nor narrated in this run.

For all three files, checks covered segment order/completeness, WAV and frozen-sample hashes, and total frames including 0,25 s pauses. Assembled WAV PCM was compared byte-for-byte with source segments. All MP3 files were fully decoded. Maximum continuous silence was 1,12 s. Comparing each segment with both reference voices found no role inversions. The smallest similarity margin in favor of the correct voice was about 0,025 in every case. This is a relative signal from one speaker encoder.

Whisper base without prompting processed all 495 turns. Median text similarity was 0,899 for RU25, 0,902 for RU60, and 1,000 for EN60. EN's minimum similarity was 0,907. RU includes differences in endings, names, and the negation “а не” (rather than). In RU60, turn 155 (36:22) produced the only continuous six-word mismatch around “объяснения Феликса к „Руинам империй“ Вольнея” (Felix's explanations of Volney's Ruins of Empires). Words from this passage appear in the transcript with altered forms. For turns 70 (16:18) and 165 (38:58), ASR rendered the negation differently. These passages require listening to distinguish recognition errors from pronunciation errors. ASR and the encoder leave stress, timbre stability, and long-listening comfort unassessed.

RU 25:32 — `outputs/qwen-long-2026-11-03/ru/jobs/8ac8c32f901c4ba8/podcast.mp3` · RU 63:44 — `outputs/qwen-long-2026-11-03/ru/jobs/ade9007ab7014d26/podcast.mp3` · EN 35:13 — `outputs/qwen-long-2026-11-03/en/jobs/de1bd5a172964420/podcast.mp3` · Measurements and hashes — `outputs/qwen-long-2026-11-03/record.json` · All timestamps, texts, and transcripts — `outputs/qwen-long-2026-11-03/turn-review.json`.

## Out of memory and resume

The English check stopped after 75 of 117 segments with Metal OutOfMemory. The machine was simultaneously running two TTS processes, our analyzers, and an unrelated `llama-server` using about 19 GB. The data does not attribute the cause solely to worker count. The same job was resumed sequentially, reusing all 75 accepted WAV files. Speech analyzers ran after synthesis. Unrelated processes continued running.

The product gained a cross-project Qwen-inference lock with visible waiting and cancellation. Assembly from fully cached segments proceeds without waiting. Out-of-memory reports offer “Продолжить” (Resume), with the technical error available separately. An interprocess test without GPU checked waiting, cancellation, release on process exit, and bypass for cache and CPU narration. Other applications' memory use also affects synthesis availability.

Times in audio metadata describe the corresponding pass. EN's last-pass time includes cache-based resume. No isolated performance comparison was performed in this experiment.

## Content checking against the source

Scripts match the original saved revisions. The original EPUB's SHA-256 in both copies is `bf04d57cf243314ab770df6fcea6a9cfb1e5a281426453e23c128c5a9c3eb662`. Every reference points to an existing extracted fragment. The short Russian episode has 157 references to 17 distinct fragments, the Russian hour-long episode 399 to 75, and the English episode 152 to 65.

For semantic checking, turns from the beginning, middle, and end of each episode were compared with the EPUB text. The table gives the ID suffix after `bf04d57cf243314ab770:`.

| Turn | Fragment | What the original text supports |
|---|---|---|
| RU 25, 2 | 4 | The first letter identifies Mrs. Saville, England, Saint Petersburg, and 11 December. Walton addresses his sister as Margaret. |
| RU 25, 55 | 53 | Old De Lacey offers help. When the household returns, Felix attacks the narrator. The script correctly distinguishes the two people's actions. |
| RU 25, 107 | 87 | The Creature announces its intention to burn itself. Walton sees it leave the ship on an ice raft and disappear into the distance. |
| RU 60, 5 | 4 | Walton describes whaling voyages, hardship, and studying mathematics, the theory of medicine, and applied sciences. |
| RU 60, 132 | 41 | Victor first acknowledges a creator's duty to his creation. He says he should have cared for its happiness. |
| RU 60, 269 | 84, 87 | Walton observes the jump from the cabin window onto the ice. He does not see a fire in the ending. |
| EN 2 | 4 | Walton names the polar passage and investigation of magnetism. His interest in glory is explicit. Interpretation of the narrator's function is labeled as interpretation. |
| EN 59 | 45 | The narrator secretly collects firewood for the family. Felix discovers the supply and gains time for other activities. |
| EN 116 | 87 | In the Creature's speech, the fire and destruction of its remains are still in the future. The script preserves the distinction between intent and Walton's observation. |

Other claims were not rechecked line by line this time. Earlier reading results for these same revisions appear in [content acceptance](2026-11-01-long-podcasts.md#content-review-of-earlier-episodes).

## Manual stress-mark experiment

Both voices recorded “Я вижу замок” (I see a castle/lock) with pinned seed 42. Each role received five inputs: normal spelling, two placements of combining accent U+0301, and two placements of `+` before a vowel. 10 new segments in total, 20,57 seconds including pauses. All other parameters were identical. Local Whisper base without text prompting transcribed both normal inputs verbatim. For “зам+ок”, the word “плюс” (plus) appeared in both roles' transcripts. For all four U+0301 inputs, the recognized word differed from “замок”. A/B recording: `outputs/qwen-long-2026-11-03/stress.mp3` · Ten inputs: `outputs/qwen-long-2026-11-03/stress-input.json`.

This result does not confirm reliable manual stress-mark support. Different WAV lengths alone do not establish which syllable the model stressed. The editor does not suggest special markup for Qwen.

## Targeted correction on the real model

A separate copy of the accepted twenty-turn script saved r2 with “кто всё сделал” replaced by “кто совершил преступление” (who did it → who committed the crime) in the first turn. Preview `92bbaca45b2b4261` synthesized one turn, 16,08 seconds. Full render `2ed49366e0cd4222` then reused 20/20 cached segments, including this preview. Nineteen unchanged keys match r1. The assembled episode is 4:56. Reassembly took 0,544 s without repeat synthesis. Both MP3 files were fully decoded, and WAV hashes were checked. The corrected word's sound was not assessed by listening.

Full updated episode: `outputs/turn-correction-2026-11-03/workspace/jobs/2ed49366e0cd4222/podcast.mp3` · Turn preview: `outputs/turn-correction-2026-11-03/workspace/jobs/92bbaca45b2b4261/turn.mp3` · Key/file checks: `outputs/turn-correction-2026-11-03/result.json`.

## Boundaries of the completed check

The check used three existing proofread revisions of one EPUB. Content was checked selectively, and the long files were not fully listened to in this run. The proposed threshold of no more than 5% correctable turns and subjective speech quality were not checked in this experiment. There is no separate user approval of that threshold as a guarantee. At the original check date, real duration checking of newly written scripts after budget recalculation also remained open. The continuation's result is below. Targeted preview is an optional way to correct an observed defect.

## Fresh scripts after budget recalculation

The 03.11.2026 continuation used lower and upper boundaries: RU20 and EN60 from the same complete EPUB. New scripts were written by official stable Codex CLI 0.162.1. TTS remained local Qwen Base with the same voices. Artifacts are in qwen-duration-2026-11-03 — `outputs/qwen-duration-2026-11-03`, with inputs/jobs in `cases.json`. The first attempts actually read all 89 available fragments. Later attempts reused accepted notes for the same source, focus, and runner with strictly matching fingerprints. No cross-job reading cache was added to the product.

The first new RU20 produced 2 312 words against a 2 415 budget and audio **20:02**. Before synthesis, one turn was aligned with the male voice: “Я бы сказала” → “Я бы сказал”. The first EN60 produced 7 948 words against an 8 550 budget, accumulating the shortfall allowed separately for each section. Its expected duration from the earlier measurement was below 54 minutes. This English draft was not narrated.

For new scripts, `dialogue_version=3` distributes remaining words among remaining sections and checks the last section against the total budget as well, with 2% tolerance. One bounded substantive section correction remains. The gender hint matches the two ready-made voices. Historical jobs retain their earlier prompts, budgets, and checkpoints. Correction asks for supported details to be added and repetitions removed. There is no automatic audio truncation or silence insertion to reach the target duration.

The repeated RU20 (`1504d3086b024e16` r1, render `b66e649d25fa4b5f`) contains 2 418 words against a 2 415 budget and 93 turns, without manual editing. It produced **20:43**, passing the duration criterion. All 93 segments were checked by ASR and comparison with both voices. No inversions were found, and the minimum correct-voice margin was about 0,0235. WAV was reconstructed byte-for-byte from segments and pauses. MP3 was fully decoded. Maximum silence was 1,00 s. Median ASR similarity was 0,912. Ambiguous differences remain at turns 24 (5:15), 36 (8:02), 38 (8:22), and 92 (20:17). Recognition alone is not used to declare these pronunciation errors.

The English script with the new word allocation produced 8 469 words, but selective checking found incorrect references despite correct descriptions of events. For example, materials from dissecting rooms/slaughterhouses are described in source fragment 21, while the script cited 17/18. Primary notes had the correct IDs. Later note merging lost the connection between individual facts and the shared ID list. This draft was not narrated either. For new podcasts, series, and slides, `reading_version=2` retains separate notes with one original ID during compression. A test rejects a merged reference and checks resume without rereading. Earlier schemas and checkpoints are preserved. This is structural protection. A schema still does not establish semantic accuracy of a model answer.

The English script after this fix was read in full. One incorrect claim was found in r1: absence of detail about Werther's influence in short notes was presented as absence from the source. The original explicitly describes the book's influence. Turn 83 was corrected using fragment 51, and r2 (`0dbd48090051461d`) saved: 8 466 words, 170 turns. Original r1, references, and the other 169 turns were retained. `source-review.json` records seven English and five Russian control comparisons, plus rejected references from the intermediate EN draft. Overall editor-free generation quality is not declared accepted from one material.


### Fresh-check result

| New episode | Words / budget | Finished audio | Deviation from request | Rate | Synthesis | Maximum silence |
|---|---:|---:|---:|---:|---:|---:|
| RU20, r1 | 2 418 / 2 415 | 20:43 | +3,61% | 116,68 words/min | 9:36 | 1,00 s |
| EN60, r2 | 8 466 / 8 550 | 55:25 | −7,64% | 152,77 words/min | 23:40 | 0,88 s |

Both episodes meet ±10% of the request and the 20-60-minute boundaries. These are real new scripts and complete renders. The result does not guarantee the same rate for arbitrary text. Synthesis ran sequentially without networking. ASR and the speaker encoder ran afterward. There were no new OOM events, missing segments, or repeat synthesis in these two final jobs.

All 263 turns of the two final episodes were checked by ASR and compared with both pinned voices. Automatic comparison found no role inversions. Minimum correct-voice margins were 0,0235 RU and 0,0236 EN. English median text similarity was 1,000, with a minimum of 0,833. Alignment found no continuous run of six or more unmatched words in either episode. These are diagnostic signals rather than listening assessment. Segment order, text, and hashes, pinned references, and the original were checked. Both WAV PCM streams were reconstructed byte-for-byte with pauses, and both MP3 files fully decoded.

RU 20:43 — `outputs/qwen-duration-2026-11-03/v3-ru/jobs/b66e649d25fa4b5f/podcast.mp3` · EN 55:25 — `outputs/qwen-duration-2026-11-03/v4-en/jobs/0e2d5c10b8be4cfd/podcast.mp3` · Summary measurements — `outputs/qwen-duration-2026-11-03/quality-checks.json` · Texts with timestamps and ASR differences — `outputs/qwen-duration-2026-11-03/listening-guide.md`.

Full offline run: **414 passed**. After the last small applicability fix, 72 CLI/pipeline/reading checks passed separately. Ruff check/format and diff check pass. Clean-environment installation and wheel were not rebuilt in this continuation. Real new writing was checked through Codex. Other text runners were not rerun. The working stable executable is identified in the handover. Global configuration was unchanged.

Real checking of the new budget is complete. Full listening, pronunciation, and overall correction rate are not accepted by this run. Personal M4 was subsequently cancelled under D027. Zero manual edits in final RU and one substantive edit among 170 EN turns do not confirm a listening threshold of ≤5% or quality on other materials.


## Full substantive review of finished episodes

The next M4 continuation on 03.11.2026 used the two already finished new episodes. There were no new text jobs, text-model calls, or episodes generated from scratch. All 93 Russian and 170 English turns were read. Factual claims and their cited sources were checked against original scenes. Narrator qualifications, interpretations, and uncertainty of counterfactual conclusions were preserved separately. The review covers framing letters, childhood and experience, Henry's care, the trial, the Creature's learning, murders, the agreement, the Orkneys, the wedding, pursuit, and ending. Scene-level checks, affected turns, original fragments, and their text hashes are in `outputs/qwen-duration-2026-11-03/content-audit/audit.json`. This records editorial review, not an automatic reliability metric.

In English turn 64, the person who fled the hut was called a shepherd. Original fragment 43 explicitly calls him an old man. The narrator merely supposes that the hut was built for a shepherd. The wording was replaced with “an old man”, reference 43 added, and reference 44 for observing the family retained. Other spoken words in this revision were unchanged.

References were added for precise detail checking: RU 60 — fragment 63 naming the Orkney Islands; EN 116 — 57 with compassion during discussion of the agreement; EN 117 — 59 with the scientific purpose of the England trip; EN 118 — 64 with work and concerns on the island; EN 142 — 74 with Elizabeth's letter about freely choosing marriage. When uncertain, the full needed context was checked: for example, refusing food, helping with firewood, and clearing snow really do belong to the Creature; the word about cowardice also appears in Victor's speech; fragment 31 also includes the expectation of Justine's acquittal. These suspicions did not become unnecessary edits.

| Episode | Saved revision | Finished audio | Cache | New spoken turns |
|---|---|---:|---:|---:|
| RU | `1504d3086b024e16` r1 → r2, render `6b337889d7ac44c9` | 20:43 | 93/93 | 0 |
| EN | `0dbd48090051461d` r2 → r3, render `df7c340dcae84af8` | 55:24 | 169/170 | 1 |

The original EPUB, earlier revisions, and MP3 files were retained. All unchanged segment keys matched. The complete Russian WAV is byte-for-byte identical to the previous one. Only turn 64's key changed in English. Its new synthesis was checked by unprompted ASR: text similarity 1,000, with no inversion found in voice comparison. For the other 262 turns, earlier ASR/encoder results were accepted only on matching text, keys, and WAV SHA-256. There was no repeat inference. New complete WAV files were reconstructed from segments, and MP3 files fully decoded. Both durations meet tolerance. Maximum silence is 1,00 s RU and 0,88 s EN. Assembly took 2,080 s RU and 16,059 s EN.

Current RU 20:43 — `outputs/qwen-duration-2026-11-03/v3-ru/jobs/6b337889d7ac44c9/podcast.mp3` · Current EN 55:24 — `outputs/qwen-duration-2026-11-03/v4-en/jobs/df7c340dcae84af8/podcast.mp3` · Editorial review and changes — `outputs/qwen-duration-2026-11-03/content-audit/audit.json` · Audio metadata — `outputs/qwen-duration-2026-11-03/content-audit/quality-checks.json` · Current text and timestamps — `outputs/qwen-duration-2026-11-03/content-audit/listening-guide.md`.

Substantive review of these two episodes is complete. Application code and dependencies were unchanged in this step. The full 414 offline suite was not rerun. Full listening assessment is not established by this check. Personal M4 was subsequently cancelled under D027: Russian ambiguous ASR passages remain at 24, 36, 38, and 92, and recognition does not replace assessment of stress or the overall proportion of required corrections. This substantive review created no separate new development scope.
