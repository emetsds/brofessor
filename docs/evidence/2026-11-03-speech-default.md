# Qwen3-TTS Base with ExNihilus as the default

Historical report. Current requirements and boundaries are in the [specification](../specification.md); decisions and cancellations are in the [Decision log](../decision-log.md). References to later stages describe the state at the time of the experiment.

On 03.11.2026, the user rated the Russian five-minute sample “Ключ, письмо и хороший детектив” (“The Key, the Letter, and a Good Detective”) excellent and instructed that this method become the default. Profile `qwen3-base` was selected. The Russian pair and method were accepted for further work.

## What was integrated

Qwen3-TTS Base 1.7B 4-bit, revision `37e955a1deb861c088ae5f3a67043185f3d1a60c`, was added to the shared catalogue. Weights and codec occupy 2 336 074 141 bytes. The ExNihilus dependency adds 2 055 052 bytes. It includes male and female WAVs for RU and EN, original transcripts, NOTICE, and the CC0 text. All resources are pinned to revision `5103f8988ee936525fbfb6dc10061bbabd1d584e`.

New application profiles and direct audio renders select Base by default. Explicit selection of another engine is respected. `qwen3-base` is installed and selected in the owner's user profile. An open Streamlit session picks up CLI model-selection changes on the next rerun.

CLI and UI use the shared download/render service. A new user only needs to download the model. Language selection supplies the corresponding ExNihilus samples. On job creation, the service verifies every WAV's SHA-256, copies samples into the project, and saves exact transcripts. The job then depends on project copies. It can resume after moving the project and deleting the original voice pack from the shared cache.

The audio-segment key includes the particular speaker sample's SHA-256 and text. Replacing host preserves the guest cache. A changed shared default applies to a new render; a saved job uses its own snapshot.

The standard adapter calls Base ICL with `ref_audio`, `ref_text`, and explicit language. Temperature 0.7, top_p 0.9, top_k 50, repetition penalty 1.5, seed 42. The existing function splits a long edited turn at sentences and words into at most 300 RU or 400 EN characters. All words are preserved. Exhausting 600 tokens or returning an empty part stops the turn before checkpoint writing. MLX memory is limited to 10 GiB, wired memory to 8 GiB, and cache to 128 MiB.

## Checks

**386 offline tests**, Ruff check, Ruff format check, and diff checks passed. New checks cover downloading the model with samples, CLI/UI defaults, transfer of frozen inputs, retention of the other speaker's cache, corrupted WAVs, correct ICL calls, long-text splitting, token exhaustion, and an empty part result.

Real checks were also performed in an isolated profile on Mac M4 / 32 GiB with MLX Audio 0.6.3, using the ordinary CLI, SQLite queue, and detached worker.

| Scenario | Result |
|---|---|
| Standard Base and ExNihilus download | Completed. Large weights reused after hash checks; missing voices obtained through a download job |
| Two Russian turns | 10.65 s audio, 9.947 s rendering |
| Two English turns | 9.85 s audio, 6.145 s rendering |
| Accepted 20-turn Russian script | 4:54 audio, 192.757 s rendering |
| English render repeated with a new request key | Both turns cached, MP3 byte-identical |
| Twenty turns repeated with a new request key | All 20 turns cached, 0.631 s, MP3 byte-identical |

All final MP3s were fully decoded, and WAV hashes checked against checkpoint metadata. CPU Whisper base without text hints checked 24 unique turns. The four short RU/EN turns were recognized verbatim after normalization. Longer text still has word and ending discrepancies; ASR does not confirm stress placement. The English pair was selected from the same set and passed a technical trial; subjective acceptance remained open. Long 20–60-minute Base episodes were not rebuilt in this slice; the [later check](2026-11-03-qwen-long-dialogues.md) is described separately.

The original accepted sample used a seed varying by turn index and constant gain per speaker. The product adapter uses fixed seed 42 for deterministic segments and ordinary full-render assembly. The new recording therefore differs bit-for-bit from the experimental sample.

[Original accepted sample](2026-11-03-speech-default.md#original-approved-sample), real-check records: `outputs/qwen-default-integration/real-results.json`, transcripts: `outputs/qwen-default-integration/real-asr.json`, activation state: `outputs/qwen-default-integration/activation.json`.

## Original approved sample

On 03.11.2026, an original fictional conversation, “Ключ, письмо и хороший детектив” (“The Key, the Letter, and a Good Detective”), was created at the user's request. The goal was to assess timbre, Russian stress, and comfort over several minutes of speech. This section records the initial trial before later approval of the Russian sample; it does not establish quality for arbitrary long episodes.

### Result

- MP3, 4:52 — `outputs/qwen-dialogue-2026-11-03/qwen-exnihilus-dialogue.mp3`
- WAV, 24 kHz PCM16 — `outputs/qwen-dialogue-2026-11-03/qwen-exnihilus-dialogue.wav`
- Timestamped text — `outputs/qwen-dialogue-2026-11-03/script.md`
- Player and pronunciation-check points — `outputs/qwen-dialogue-2026-11-03/listening-guide.md`

The final revision has 631 words and 20 complete turns. The male voice speaks first, then speakers alternate. Two self-contained digressions were removed from the initial text to achieve about five minutes at the standard rate. The complete original 24 turns, their synthesis, and hashes remain in the experiment directory. The final revision is stored separately in `listening-input.json`.

The dialogue consists of separate model calls for complete turns. Each call reuses the same voice sample afresh. The check concerns a finished conversation composed of many turns, including timbre stability toward the end.

### Model and inputs

[Qwen3-TTS 1.7B Base 4-bit for MLX](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-Base-4bit/tree/37e955a1deb861c088ae5f3a67043185f3d1a60c), revision `37e955a1deb861c088ae5f3a67043185f3d1a60c`. Weights from the previous short experiment were reused. Before execution, all files were rechecked against pinned Git/LFS hashes.

Two complete Russian [ExNihilus](https://huggingface.co/ExNihilus/qwen3-tts-reference-voices/tree/5103f8988ee936525fbfb6dc10061bbabd1d584e) WAVs were used with original transcripts and verified SHA-256. The male sample is 12.24 s, the female 10.88 s. The CC0 license and provenance description are saved beside the result. Original samples were not added to the MP3.

Standard ICL receives `ref_audio` and `ref_text`. Language `russian`, temperature 0.7, top_p 0.9, top_k 50, repetition penalty 1.5, seed 42 + turn index. The check was limited to 600 tokens and 240 seconds of computation per turn. No generation reached those limits.

The text retains “ё” and ordinary punctuation. No manual stress marks or RUAccent were supplied to Qwen. Context examples include “старый замок”, “в дверном замке”, “звонит соседке”, and “в последней главе” (a castle/door-lock ambiguity, calling a neighbor, and the last chapter).

### Conditions and checks

Mac M4, 32 GiB, MLX Audio 0.6.3 / MLX 0.32.4. One local TTS process. Before execution, Ollama reported an empty loaded-model list. Inference used local paths, HF/Transformers offline mode, and a ban on socket.connect. No weights were downloaded during the experiment.

The original 24 turns took 167.1 s of computation; the final revision's 20 turns took 138.1 s. Model loading took 3.16 s. Accumulated MLX peak was 7.18 GB. This is an MLX metric; full process RAM and power consumption were not measured.

There is a 0.25 s pause between turns. The male channel received constant gain of 1.97 dB, the female −2.73 dB, measured over the fully assembled speaker tracks. Rate, pitch, and spectrum were preserved. Final MP3: −23.45 LUFS, true peak −3.31 dBTP. WAV and MP3 were fully decoded and hashes checked. No samples at the PCM limit were found in selected original turns; the longest continuous silence below −60 dBFS was 0.78 s.

Local CPU Whisper base without a text hint checked all 24 original turns. In the final revision, 8 of 20 turns matched normalized words verbatim. Other discrepancies were examined in text. Most concern endings and joined recognition, such as “на столе” → “насталя” and “с облегчением” → “соблегчением”. “главе” → “голове” also occurs and is separately marked for listening. This check found no whole-sentence omissions. ASR does not confirm correct stress placement or comfort.

The directory retains `manifest.json`, `references.json`, original and final texts, each turn's WAV/JSON, ASR, and a discrepancy overview. The entire experiment, including audio, is excluded from Git. The Base product adapter and selection of permanent voices remain part of unfinished listening acceptance.
