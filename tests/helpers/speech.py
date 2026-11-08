"""Synthetic recordings for the current Qwen Base catalog; no network or weights."""

import hashlib
import io
import wave

from brofessor.infrastructure.speech import catalogue as speech_models


def install_presets(monkeypatch):
    spec = speech_models.get("qwen3-base")
    pack = spec["dependencies"][0]
    directory = speech_models.snapshot(pack)
    directory.mkdir(parents=True, exist_ok=True)
    files = {}
    for references in spec["preset_references"].values():
        for reference in references.values():
            output = io.BytesIO()
            with wave.open(output, "wb") as audio:
                audio.setparams((1, 2, 24000, 0, "NONE", "none"))
                audio.writeframes(b"\x01\x00" * 72000)
            data = output.getvalue()
            (directory / reference["file"]).write_bytes(data)
            files[reference["file"]] = len(data)
            reference["sha256"] = hashlib.sha256(data).hexdigest()
    pack["files"] = files
    pack["download_bytes"] = sum(files.values())
    monkeypatch.setattr(speech_models, "CATALOG", [spec])
    return spec
