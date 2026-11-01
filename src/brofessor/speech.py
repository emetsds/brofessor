"""Local speech engines; segment caching and assembly belong to media.py."""

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
    if spec.get("engine") == "f5":
        try:
            return (
                "f5-tts/"
                + importlib.metadata.version("f5-tts")
                + "/torch/"
                + importlib.metadata.version("torch")
            )
        except importlib.metadata.PackageNotFoundError:
            return "unavailable"
    package = "torch" if spec.get("engine") == "silero" else "mlx-audio"
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _silero_text(text):
    return text.translate(str.maketrans({"„": '"', "“": '"', "”": '"', "‘": "'", "’": "'"}))


def validate_text(spec, text):
    if spec.get("engine") == "silero" and re.search(
        r"[^\sа-яёА-ЯЁ+.,!?;:—–‑\-()«»\"'…]", _silero_text(text)
    ):
        raise ValueError(
            "Silero CIS Base needs numbers and Latin names or symbols written as Russian words; "
            "edit the draft or choose Qwen3-TTS"
        )


def load(spec, location):
    try:
        if spec.get("engine") == "f5":
            return _F5(spec, location)
        if spec.get("engine") == "silero":
            return _Silero(spec, location)
        if spec.get("engine", "qwen3-mlx") == "qwen3-mlx":
            return _Qwen(spec, location)
        raise SpeechError(f"Unsupported speech engine: {spec['engine']}")
    except ImportError as error:
        extra = {"silero": "silero", "f5": "f5"}.get(spec.get("engine"), "speech")
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
            audio = self.model.apply_tts(
                text=_silero_text(text), speaker=voice, sample_rate=self.sample_rate
            )
        _check(cancelled)
        return audio.cpu().numpy(), self.sample_rate


class _F5:
    def __init__(self, spec, location):
        import torch
        from f5_tts.infer.utils_infer import load_model, load_vocoder
        from f5_tts.model import DiT
        from .speech_models import installed_path

        if not torch.backends.mps.is_available():
            raise SpeechError("F5-TTS currently requires an Apple Silicon Mac with Metal")
        self.device = "mps"
        self.spec = spec
        vocoder_path = installed_path(spec["dependencies"][0])
        if vocoder_path is None:
            raise SpeechError("Download the selected model and its Vocos weights first")
        self.model = load_model(
            DiT,
            spec["model_config"],
            str(location / spec["checkpoint"]),
            vocab_file=str(location / spec["vocab"]),
            device=self.device,
        )
        self.vocoder = load_vocoder(is_local=True, local_path=str(vocoder_path), device=self.device)
        self.references = {}

    def synthesize(self, text, voice, language, cancelled):
        import hashlib
        from pathlib import Path
        import numpy as np
        import soundfile as sf
        import torch
        from f5_tts.infer.utils_infer import infer_batch_process

        ref = self.spec["references"][voice]
        if voice not in self.references:
            path = Path(ref["path"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
                raise SpeechError("Saved voice sample is damaged")
            audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
            self.references[voice] = (
                torch.from_numpy(audio.mean(axis=1)).unsqueeze(0),
                sample_rate,
            )
        _check(cancelled)
        torch.manual_seed(self.spec["settings"]["seed"])
        # Supplying the exact transcript avoids upstream ASR and its implicit downloads.
        # Sequential streaming keeps MPS bounded and checks cancellation between chunks.
        seconds = ref["duration_seconds"]
        budget = max(40, int(len(ref["text"].encode("utf-8")) / seconds * (22 - seconds)))
        batches, current = [], ""
        for word in text.split():
            candidate = (current + " " + word).strip()
            if current and len(candidate.encode("utf-8")) > budget:
                batches.append(current)
                current = word
            else:
                current = candidate
        if current:
            batches.append(current)
        chunks = []
        for audio, sample_rate in infer_batch_process(
            self.references[voice],
            ref["text"],
            batches,
            self.model,
            self.vocoder,
            device=self.device,
            streaming=True,
            progress=None,
            nfe_step=self.spec["settings"]["nfe_step"],
            speed=self.spec["settings"]["speed"],
        ):
            _check(cancelled)
            chunks.append(audio)
        if not chunks:
            raise SpeechError("F5-TTS returned no audio")
        return np.concatenate(chunks), sample_rate
