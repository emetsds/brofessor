"""Two local speech engines; segment caching and assembly belong to media.py."""

import importlib.metadata
import re


class SpeechError(RuntimeError):
    """An unavailable engine or unusable generated audio."""


class SpeechCancelled(SpeechError):
    """Cancelled at the next engine checkpoint."""


def _check(cancelled):
    if cancelled and cancelled():
        raise SpeechCancelled("Rendering cancelled; completed segments are preserved")


def runtime(spec):
    package = "torch" if spec.get("engine") == "silero" else "mlx-audio"
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def validate_text(spec, text):
    if spec.get("engine") == "silero" and re.search(r"[^\sа-яёА-ЯЁ+.,!?;:—–‑\-()«»\"'…]", text):
        raise ValueError(
            "Silero CIS Base needs numbers and Latin names or symbols written as Russian words; "
            "edit the draft or choose Qwen3-TTS"
        )


def load(spec, location):
    try:
        if spec.get("engine") == "silero":
            return _Silero(spec, location)
        if spec.get("engine", "qwen3-mlx") == "qwen3-mlx":
            return _Qwen(spec, location)
        raise SpeechError(f"Unsupported speech engine: {spec['engine']}")
    except ImportError as error:
        extra = "silero" if spec.get("engine") == "silero" else "speech"
        raise SpeechError(
            f"Install local speech support: uv sync --extra {extra}: {error}"
        ) from error
    except SpeechError:
        raise
    except Exception as error:
        raise SpeechError(f"Cannot load local speech model: {error}") from error


class _Qwen:
    def __init__(self, spec, location):
        from mlx_audio.tts.utils import load_model

        self.model = load_model(str(location))
        self.settings = spec["settings"]
        if not callable(getattr(self.model, "generate_custom_voice", None)):
            raise SpeechError("Speech model must support Qwen3 CustomVoice preset voices")

    def synthesize(self, text, voice, language, cancelled):
        import mlx.core as mx
        import numpy as np

        mx.random.seed(self.settings["seed"])
        chunks, tokens = [], 0
        for result in self.model.generate_custom_voice(
            text=text,
            speaker=voice,
            language={"ru": "Russian", "en": "English"}[language],
            stream=True,
            streaming_interval=1.0,
            temperature=self.settings["temperature"],
            max_tokens=self.settings["max_tokens"],
        ):
            _check(cancelled)
            tokens += result.token_count
            chunks.append(np.asarray(result.audio, dtype=np.float32).reshape(-1))
        if tokens >= self.settings["max_tokens"]:
            raise SpeechError("Speech hit the generation limit; split or revise this turn")
        if not chunks:
            raise SpeechError("Speech model returned no audio")
        return np.concatenate(chunks), self.model.sample_rate


class _Silero:
    def __init__(self, spec, location):
        import torch

        torch.set_num_threads(4)
        self.model = torch.package.PackageImporter(
            str(location / next(iter(spec["files"])))
        ).load_pickle("tts_models", "model")
        self.model.to(torch.device("cpu"))
        self.sample_rate = spec["settings"]["sample_rate"]
        if not set(spec["voices"].values()) <= set(self.model.speakers):
            raise SpeechError("The installed Silero model does not contain the selected voices")

    def synthesize(self, text, voice, language, cancelled):
        import torch

        _check(cancelled)
        with torch.inference_mode():
            audio = self.model.apply_tts(text=text, speaker=voice, sample_rate=self.sample_rate)
        _check(cancelled)
        return audio.cpu().numpy(), self.sample_rate
