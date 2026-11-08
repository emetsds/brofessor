"""Local speech engines; segment caching and assembly belong to media.py."""

import importlib.metadata

from brofessor.contracts.content import ContentLanguage
from brofessor.infrastructure.speech.contracts import SpeechEngine


class SpeechError(RuntimeError):
    """An unavailable engine or unusable generated audio."""


class SpeechCancelled(SpeechError):
    """Cancelled at the next engine checkpoint."""


def _check(cancelled):
    if cancelled and cancelled():
        raise SpeechCancelled("Rendering cancelled; completed segments are preserved")


class _QwenBase:
    def __init__(self, spec, location):
        import mlx.core as mx
        from mlx_audio.tts.utils import load_model

        mx.set_memory_limit(10 * 1024**3)
        mx.set_wired_limit(8 * 1024**3)
        mx.set_cache_limit(128 * 1024**2)
        self.model = load_model(str(location))
        if (
            self.model.config.tts_model_type != "base"
            or not self.model.speech_tokenizer.has_encoder
        ):
            raise SpeechError("Qwen3 Base needs its voice-cloning encoder")
        self.settings = spec["settings"]
        self.references = spec["references"]

    def synthesize(self, text, voice, language, cancelled):
        import hashlib
        from pathlib import Path

        import mlx.core as mx
        import numpy as np

        from brofessor.features.podcasts.writer import split_turns

        ref = self.references[voice]
        if hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest() != ref["sha256"]:
            raise SpeechError("Saved voice sample is missing or damaged")
        options = {k: v for k, v in self.settings.items() if k not in ("seed", "segment_chars")}
        turns = split_turns([{"text": text}], self.settings["segment_chars"][language])
        mx.random.seed(self.settings["seed"])
        chunks = []
        try:
            for turn in turns:
                _check(cancelled)
                tokens = 0
                part = []
                for result in self.model.generate(
                    text=turn["text"],
                    lang_code={ContentLanguage.RU: "russian", ContentLanguage.EN: "english"}[
                        language
                    ],
                    ref_audio=ref["path"],
                    ref_text=ref["text"],
                    stream=False,
                    verbose=False,
                    **options,
                ):
                    _check(cancelled)
                    tokens += result.token_count
                    part.append(np.asarray(result.audio, dtype=np.float32).reshape(-1))
                if tokens >= options["max_tokens"]:
                    raise SpeechError("Speech hit the generation limit; split or revise this turn")
                if not part or not any(chunk.size for chunk in part):
                    raise SpeechError("Qwen3 Base returned no audio for a speech part")
                chunks.extend(part)
            return np.concatenate(chunks), self.model.sample_rate
        finally:
            mx.clear_cache()


def runtime(spec):
    try:
        return importlib.metadata.version("mlx-audio")
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def load(spec, location):
    if spec["engine"] != SpeechEngine.QWEN_BASE:
        raise SpeechError(f"Unsupported speech engine: {spec['engine']}")
    try:
        return _QwenBase(spec, location)
    except ImportError as error:
        raise SpeechError(
            f"Install local speech support: uv sync --extra ui --extra speech: {error}"
        ) from error
    except SpeechError:
        raise
    except Exception as error:
        raise SpeechError(f"Cannot load local speech model: {error}") from error
