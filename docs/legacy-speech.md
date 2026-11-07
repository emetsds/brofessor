# Restoring older speech profiles

The supported speech profile is `qwen3-base` with ready-to-use ExNihilus voices.
Older profiles are retained for reproducing existing projects and their saved
model specifications. They are hidden from the regular model list and UI.
Saved settings naming a retired or unknown profile resolve to the current default.

## Restore a historical job

Open the original project. Its render job records the model revision, settings
and, for reference-based engines, the project-relative voice samples and transcripts.
Install the optional dependencies required by that engine and download its exact
profile or saved model reference.

| Historical ID | Install extra | Language | Weight license |
|---|---|---|---|
| `qwen3-0.6b` | `speech` | RU / EN | Apache-2.0 |
| `qwen3-1.7b` | `speech` | RU / EN | Apache-2.0 |
| `silero-cis-base` | `silero` | RU | MIT |
| `silero-ru` | `silero` | RU | CC-BY-NC-SA-4.0 |
| `kokoro-ru` | `russian-speech` | RU | OpenRAIL |
| `f5-tts` | `f5` | EN | CC-BY-NC-4.0 |
| `f5-tts-russian` | `f5` | RU | CC-BY-NC-4.0 |
| `espeech-rl-v2` | `f5` | RU | Apache-2.0, declared upstream |

For example, restore a failed or interrupted CustomVoice 1.7B job with its saved
profile. Retain the extras needed by other engines in the environment when running
`uv sync`.

```sh
uv sync --locked --python 3.12 --extra ui --extra speech
uv run --no-sync brofessor -w /absolute/project tts download qwen3-1.7b --wait
uv run --no-sync brofessor -w /absolute/project job resume RENDER_JOB_ID
```

An explicit legacy render is also available for rebuilding a saved draft.

```sh
uv run --no-sync brofessor -w /absolute/project draft render DRAFT_ID --tts-model qwen3-1.7b --wait
```

`tts use` accepts currently supported profiles. For historical jobs, use their
recorded model and resume operation, or specify the model on an explicit render.

## Historical F5 voice settings

Frozen render jobs use their own copies in `voice-samples/`. To explicitly rebuild
an old draft with F5 or ESpeech, the corresponding local voice preferences can be
restored through the compatibility command `tts voice`. It is hidden from the
regular help. Supply PCM16 WAV, 2–20 seconds, with the exact spoken transcript and
permission to use the recording.

```sh
uv sync --locked --python 3.12 --extra ui --extra speech --extra f5
uv run --no-sync brofessor tts voice set host --language ru --audio host.wav --text "Exact words in host.wav."
uv run --no-sync brofessor tts voice set guest --language ru --audio guest.wav --text "Exact words in guest.wav."
uv run --no-sync brofessor -w /absolute/project tts download f5-tts-russian --wait
uv run --no-sync brofessor -w /absolute/project draft render DRAFT_ID --tts-model f5-tts-russian --wait
```

The original Russian Silero CIS Base expects manual `+` stress and spelled-out
numbers and Latin names. The later Silero RU and Kokoro RU profiles have their own
text preparation. Preserve the job's saved text, model specification and cached
segments when restoring it.

The historical listening reports record concrete limitations and source licenses.
See [Russian voice comparisons](experiments/russian-voice-samples.md),
[Kokoro and Silero RU](experiments/kokoro-silero-ru.md) and
[F5 Russian](experiments/f5-russian-and-ollama-address.md).
