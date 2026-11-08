# Russian speech selection and catalogue simplification

Historical result. Support for earlier internal formats and profiles was cancelled on 08.11.2026 ([D034](../decision-log.md)); the archives, reference baselines, and legacy adapters mentioned here were removed. These instructions are not the current recovery path.

History of experiments on 01–03.11.2026 on Mac M4 / 32 GiB. The current choice is described by [D011–D012](../decision-log.md#d011-03112026--qwen-base-with-exnihilus-by-default) and the [specification](../specification.md#support-boundaries). This record collects the rationale from the earlier media pilot, voice comparisons, research, and KISS audit. Questions open at the time of those experiments do not form the current work queue.

## First media pilot

On 01.11, the self-authored synthetic chapter `tests/fixtures/chapter.md` was used. Qwen CustomVoice, the segmented WAV cache, FFmpeg, and an independent worker confirmed the technical feasibility of local narration. The pilot did not compare the best models on the market or accept pronunciation by listening. The subsequent [long check](2026-11-01-long-podcasts.md) measured duration and recovery separately from subjective quality.

## Initial models and limitations

- Silero V5 CIS Base was selected as the MIT branch. It requires manual `+` stress marks and numbers/Latin names written out as words. The main Russian Silero is a different branch with a different license. The user rated stress placement in the CIS pilot negatively.
- Qwen CustomVoice had built-in fixed voices. In some Russian Qwen/F5 trials, the user heard excessive emotion and theatricality. Those F5 trials used synthetic Qwen references. Whether the assessment transfers to F5 with other recordings was not checked.
- F5-TTS v1 is English, while F5-TTS Russian v2 and ESpeech RL-V2 are Russian profiles of one adapter with Vocos. F5 ran on Metal, and an exact reference transcript eliminated ASR. F5 weights have NC conditions; ESpeech RL-V2 upstream stated Apache-2.0. Saved jobs pinned WAV/transcript and reused unchanged segments.
- Individual short trials established neither hour-long episode quality nor one model's superiority. Recovery instructions and exact legacy IDs are in the earlier README (section removed by D034).

## Kokoro and Silero RU

On 02.11, after user permission, Kokoro RU, the main Russian Silero, and RUAccent preparation were checked. Code, weights, and resources were pinned separately. Original script text was retained, and prepared text was recorded in segment metadata.

Manual stress marks were used in the five-minute comparison on the same book material. Kokoro produced 5:40, Silero 4:31. The user preferred Silero but did not accept the overall quality. A catalogue of technically available options was not a proven selection of the best Russian speech.

Product voices in that historical slice were Kokoro Dima/Sveta and Silero Aidar/Xenia. Eugene/Kseniya were used in a separate comparison, not as new defaults. Local materials: `outputs/book-tts-comparison-2026-11-02/`. The main Russian Silero uses CC-BY-NC-SA-4.0 and Kokoro RU uses OpenRAIL. The CIS Base license does not automatically extend to them.

## Fish and VoxCPM2 without ready-made references

On 02.11, Fish S2 Pro and VoxCPM2 were actually downloaded for one Russian excerpt. In an isolated Fish trial, the generic instruction was spoken aloud. The working variant used native inline tags. VoxCPM2 cut off the long trial, so short sections were added to complete the result. This was explicitly not a seamless successful long run.

The user heard two female voices in Fish and required ready-made stable voices without preparing references themselves. Labeling the first as male reflected the request, not confirmed sound. At the time of research, [Fish inference](https://speech.fish.audio/inference/) described random timbre without a reference. Installed MLX `generate` did not provide selection through `voice`. This proposed default pair failed the check. The proposed synthetic Eugene reference was cancelled before creation.

## Dialogs and comparison of three engines

After research into licensed sources, the user separately permitted personal noncommercial experiments and preferred Dialogs neutral. The [Dialogs source](https://huggingface.co/datasets/langswap/dialogs-ru-emotional-conversations), revision `a74ff44d8d27ca3d21098ea3ed4d31a32923fbdd`, published actor consent and OpenRAIL terms. Short Fish trials with Dima and Sveta were rated positively. Full recordings of 11,19 and 11,43 s with exact transcripts were used for the main pair.

The same Russian material was then synthesized with Fish, OmniVoice, and VoxCPM2. Detailed parameters and licenses of this authorized comparison are below. The user's assessment was “Очень похоже звучит” (“They sound very similar”). No quality winner was determined. ASR did not establish stress placement, and parallel GPU processes did not provide a clean speed comparison.

The user approved the short Fish/Dialogs Dima and Sveta trials, then requested an engine comparison with those references. This experiment creates listening recordings. No winner or new default was selected.

### Material and conditions

The shared source was the earlier checked revision of the beginning of Part I of Chekhov's The Lady with the Dog, with Russian ё, about 800 words. Every engine used the same 23 consecutive fragments and Dima/Sveta alternation. A 0,25 s gap was added between fragments. Verbal content was not shortened. This is continuous book material assembled from phrase-level calls, not one five-minute model call.

References were the earlier full Dialogs neutral Dima (11,19 s) and Sveta (11,43 s), revision `a74ff44d8d27ca3d21098ea3ed4d31a32923fbdd`, with exact transcripts. Dialogs OpenRAIL, attribution, published actor consent, and terms are retained alongside. The user authorized a personal noncommercial experiment. Originals and previous results were not replaced.

The checked + markup is retained as `pronunciation-key-plus.txt`, but was not passed to these LLM TTS engines without a confirmed support contract: the engines predict stress placement in recordings. This record does not count as manual listening acceptance of pronunciation.

### Actual models

- Fish: `majentik/fishaudio-s2-pro-MLX-4bit@dda28aa6e33fe946826792e3feb643e9c463b75f`, earlier codec from `mlx-community/fish-audio-s2-pro-8bit@c8d4481b3f7cbfe64d855c8b7cda7739502fc3ff`, BF16 with weight-norm folding. Checked VQ codes of the full references were reused, with native reference conversation. The earlier isolated loader fix permits actual quantized embedding/fast layers under strict loading. Temperature/top_p 0.7, top_k 30, speed 1, stream 1 s.

- OmniVoice: `mlx-community/OmniVoice-bfloat16@6119f7072580cc30c3cbdf496269216b03ad9742`; 2 042 327 608 bytes explicitly downloaded, weights and codec verified against upstream LFS SHA-256, small files against Git/LFS hashes. BF16 semantics + FP32 Higgs codec (types checked in safetensors), 32 steps, guidance 2, language ru. Native preprocessing: resampling, RMS boost, and silence removal without cutting words; reference transcript retained. In installed MLX, the generic duration fallback uses a dummy English reference. Here, native `RuleDurationEstimator` receives the actual rate of our reference tokens and exact text. No subsequent change to audio speed. Full references are slightly longer than the authors' recommended 3–10 s, explicitly recorded. Comparison with shorter references has not yet been performed. The original CC-BY-NC card and codec license are retained.

- VoxCPM2: `mlx-community/VoxCPM2-8bit@d52725898a0675703f7f9ddc5a4d1a3cdbb99032`, earlier local weights. 10 inference timesteps, cfg 2. Native continuation through `prompt_audio` + `prompt_text`; this runtime ignores generic `ref_text`, which is not used instead of a native prompt. Earlier cutoffs on long text-only/synthetic-anchor trials are not presented as properties of the new complete experiment with real references.

All models used installed MLX-Audio 0.6.3 / MLX 0.32.4 on Mac M4 32 GiB. During inference, HF/Transformers were offline and socket.connect was prohibited. No cloud calls. At the start, Ollama `/api/ps` returned an empty list. No unload/stop/reconfiguration was performed. Several self-owned GPU processes ran simultaneously, so wall time and peak MLX below are observations from this experiment, not a clean comparative benchmark. Seed 42 + fragment number, identical across engines.

### Files and checks

| Engine | Duration | Sum of segment times | Peak MLX |
|---|---:|---:|---:|
| Fish S2 Pro 4-bit + BF16 codec | 5:32 | 18:57 | 5.18 GB |
| OmniVoice BF16 | 5:12 | 10:03 | 4.88 GB |
| VoxCPM2 8-bit | 5:06 | 21:38 | 9.16 GB |

Main MP3 files contain synthesis only, without actors' source recordings at the beginning. Shared loudness target, constant gain, no compression/EQ/pitch/rate changes, resampling to 48 kHz. Measured LUFS, timeline, hashes, and complete FFmpeg decoding are in the manifest. Raw segments, model specs, logs, and variants are retained in `outputs/dialogs-model-comparison-2026-11-02/`.

Full-recording players: `outputs/dialogs-model-comparison-2026-11-02/listening-guide.md` · Short comparison: `outputs/dialogs-model-comparison-2026-11-02/short-listening-guide.md`. The short Fish control was taken from previously liked files. Short OmniVoice/VoxCPM2 samples were generated anew.

All 69 fragments were checked with pinned local Whisper base for approximate text coverage. ASR differs on names, endings, and word separation. Transcripts of suspect passages were reviewed separately and recorded in `asr-review.json`. ASR does not accept stress placement, timbre transfer, or long-listening comfort.

Application code, the model catalogue, user defaults, and running servers were unchanged. Compilation of isolated scripts and `git diff --check` passed. Product offline tests were not repeated for media generation. At the experiment date, M4 awaited listening assessment. Personal acceptance was later cancelled under D027.

Dialogs — Ilya Shigabeev and Ilya Latyshev (Langswap). Built with Fish Audio.

### Feedback, licenses, and resources

User: “Очень похоже звучит” (“They sound very similar”). This assesses similarity of the three recordings. Final engine selection and accuracy of every stress mark were not declared accepted. Original feedback is recorded in `listening-feedback.json` and the manifest.

Licenses were rechecked against primary sources and retained texts for the models actually used:

- [Fish S2 Pro](https://huggingface.co/fishaudio/s2-pro/blob/main/LICENSE.md): Fish Audio Research License; personal/research noncommercial use is free. Commercial Purpose includes internal business/organization work and requires a separate written agreement. Distribution of materials/derivatives or a product containing them requires a license copy, Notice, and Built with Fish Audio.
- [OmniVoice](https://huggingface.co/k2-fsa/OmniVoice#license): Apache-2.0 code, CC-BY-NC weights (the source does not explicitly name version 4.0 here). The actually used [Higgs codec](https://huggingface.co/k2-fsa/OmniVoice/blob/main/audio_tokenizer/LICENSE) additionally has the Boson Higgs Audio 2 Community License with incorporated Meta Llama 3 terms: its own notices/attribution when distributing a product, and an expanded-license request above 100 000 annual active users of the licensee/affiliates in the previous calendar year. The whole OmniVoice stack cannot be described as Apache-2.0.
- [VoxCPM2](https://huggingface.co/openbmb/VoxCPM2#license): Apache-2.0; the author explicitly permits commercial use.
- Dialogs OpenRAIL — `outputs/dialogs-model-comparison-2026-11-02/dialogs-LICENSE.md`: separate terms for the Dima/Sveta references, including permission for commercial purposes. Distribution of the dataset/derivatives/outputs requires passing on the license text and mandatory use restrictions. This does not remove the TTS license's own restrictions.

Minimum files for the selected configurations including codec: Fish 4,45 GB, OmniVoice 2,04 GB, VoxCPM2 3,23 GB (decimal GB). Old snapshots/unused 8-bit Fish semantic weights and other experiments are excluded. Peak MLX and times are above. They are not total macOS/Python/Ollama memory or a clean speed comparison because runs were parallel. No API expenses: synthesis was local. Energy in watt-hours was not measured. Machine-readable calculations: `resource-comparison.json`. For personal use, OmniVoice is a justified candidate at similar quality. VoxCPM2 is simpler for more freely distributing weights/integration. No default decision was made. Confident speed ranking needs a separate sequential experiment.

## Freely licensed voices and comfortable timbre

On 03.11, the user prioritized quality and freely licensed code, weights, and samples. The Dmitri/OHF and Natalia/SOVA pair was rejected. This is a separate assessment of voices, not a rejection of the license or quality of every engine with other inputs.

Sources researched:

- [Dmitri/OHF](https://github.com/OHF-Voice/voice-datasets/tree/1692a7c509e35eceb5d3bd6a7581a104629ded0f): CC0, published samples and transcripts. The Mozilla page additionally instructs against identifying the speaker.
- [SOVA](https://sova.ai/dataset/) and [derived reference](https://huggingface.co/nakash1987/subly-ru-tts): the stated CC BY 4.0 requires attribution. A license label does not replace checking a particular file's provenance.
- [ExNihilus](https://huggingface.co/ExNihilus/qwen3-tts-reference-voices/blob/5103f8988ee936525fbfb6dc10061bbabd1d584e/NOTICE.md): synthetic VoiceDesign voices, WAV/text/descriptions under CC0 with explicit cloning permission. Originals were checked against author-provided hashes.
- [Vosk TTS 0.7](https://huggingface.co/alphacep/vosk-tts-ru-multi/blob/0960eb904b9035a9fdbba2882933a4f5a84c525f/README.md): built-in artificial voices and code under Apache-2.0. In a separate comparison, numeric ID 4 was closer to published M02. There was no automatic name map in the configuration.
- [RESD](https://huggingface.co/datasets/Aniemore/resd): an MIT corpus for emotion recognition. Research did not find confirmation of actor consent for permanent synthetic hosts. It was not included in the default.

One phrase was compared using Silero CIS, ESpeech with ExNihilus, and Vosk, then Qwen Base with the same ExNihilus and separately synthesized Silero references. Constant gain to −23 LUFS did not change rate, pitch, or equalization. Fundamental frequency and high-frequency content were measured as properties of short recordings, without inferring long-episode comfort. Materials: `outputs/soft-timbre-2026-11-03/`, `outputs/qwen-base-2026-11-03/`.

Short Qwen Base used ICL `ref_audio`/`ref_text`, temperature 0,7, repetition penalty 1,5, seed 42, offline, and without competing TTS. Four syntheses took 3,01–4,18 s for 5,04–5,68 s of audio. Peak MLX 6,84 GB is not the machine's total memory. Then [the five-minute dialogue was approved and the method integrated](2026-11-03-speech-default.md).

## Catalogue simplification

On 03.11, the KISS audit recommended one supported method, `qwen3-base` with ExNihilus, shared download/render operations, and separate exact legacy IDs. The user requirement was a ready result without constructing a timbre. The earlier eight profiles were hidden from ordinary selection. Their saved specifications and files were unchanged.

Unverified MOSS, CosyVoice, Drama, and other research candidates did not become integrations or tasks. Reviews of author benchmarks and speeds on other hardware did not establish quality on this Mac. A newly licensed reference does not remove restrictions of the weights, codec, and runtime themselves.

This overview replaces repetitive intermediate reports. Original details are retained in Git before the documentation reorganization. Local recordings, hashes, references, and manifests remain outside the public repository. No resynthesis was performed when moving the documentation.
