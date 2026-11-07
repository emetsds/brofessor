"""Offline RUAccent preparation and the pinned Russian Kokoro ONNX frontend."""

import gzip
import importlib.util
import json
import re
import sys
from pathlib import Path

from brofessor.contracts.content import ContentLanguage
from brofessor.infrastructure.speech.engines import SpeechError, _check

_WORDS = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9+\u0301]+")
_VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"


def _plus(text):
    return re.sub(f"([{_VOWELS}])\u0301", r"+\1", text)


def _bare(text):
    return text.replace("+", "").replace("\u0301", "").casefold().replace("ё", "е")


def preserve_text(source, accented):
    """Accept only stress/ё edits; retain source punctuation and manual stress."""
    source = _plus(source)
    original, prepared = list(_WORDS.finditer(source)), list(_WORDS.finditer(accented))
    if len(original) != len(prepared) or any(
        _bare(a.group()) != _bare(b.group()) for a, b in zip(original, prepared)
    ):
        raise SpeechError("RUAccent changed words; revise this turn or mark stress manually")
    result, end = [], 0
    for a, b in zip(original, prepared):
        word = a.group()
        if "+" not in word:
            # Keep the author's case, while allowing RUAccent to restore ё.
            letters = iter(word)
            chars = []
            for char in b.group():
                if char == "+":
                    chars.append(char)
                else:
                    old = next(letters)
                    if old.casefold() == "ё":
                        char = old
                    chars.append(char.upper() if old.isupper() else char.lower())
            word = "".join(chars)
        result.extend((source[end : a.start()], word))
        end = a.end()
    return "".join(result) + source[end:]


class _TokenizerInputs:
    """Match tokenizer v5 output to the older RUAccent ONNX input contract."""

    def __init__(self, tokenizer, session):
        self.tokenizer = tokenizer
        self.needs_types = "token_type_ids" in {i.name for i in session.get_inputs()}

    def __call__(self, *args, **kwargs):
        import numpy as np

        encoded = self.tokenizer(*args, **kwargs)
        if self.needs_types and "token_type_ids" not in encoded:
            encoded["token_type_ids"] = np.zeros_like(encoded["input_ids"])
        return encoded

    def __getattr__(self, name):
        return getattr(self.tokenizer, name)


def _load_accent(path):
    """Initialize stable RUAccent 1.5.8.3 from a complete pinned snapshot.

    Its public load() downloads unpinned resources into site-packages. Instead,
    initialize its components locally. A private package namespace lets the
    rule engine find its pinned Koziev code/data without modifying the install
    or confusing different resource revisions in the same worker.
    """
    import onnxruntime as ort
    import ruaccent

    ort.disable_telemetry_events()

    name = "_brofessor_ruaccent_" + path.name
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name,
            ruaccent.__file__,
            submodule_search_locations=[str(Path(ruaccent.__file__).parent), str(path)],
        )
        package = importlib.util.module_from_spec(spec)
        sys.modules[name] = package
        spec.loader.exec_module(package)
    else:
        package = sys.modules[name]
    accent = package.RUAccent()
    accent.tiny_mode = False
    accent.custom_dict = {}

    def dictionary(filename):
        with gzip.open(path / "dictionary" / (filename + ".json.gz")) as stream:
            return json.load(stream)

    accent.omographs = dictionary("omographs")
    accent.omographs["коса"] = ["к+оса", "кос+а"]
    accent.yo_words = dictionary("yo_words")
    accent.yo_homographs = dictionary("yo_homographs")
    accent.accents = dictionary("accents")
    accent.accents.update(accent.letters_accent)
    for model, folder in (
        (accent.omograph_model, "nn_omograph/turbo3.1"),
        (accent.accent_model, "nn_accent"),
        (accent.yo_homograph_model, "nn_yo_homograph_resolver"),
        (accent.stress_usage_predictor, "nn_stress_usage_predictor"),
    ):
        model.load(str(path / "nn" / folder), device="CPU")
        model.tokenizer = _TokenizerInputs(model.tokenizer, model.session)
    rule = __import__(name + ".rule_accent_engine", fromlist=["RuleEngine"])
    accent.rule_accent = rule.RuleEngine()
    accent.rule_accent.load(str(path / "dictionary" / "rule_engine"))
    return accent


class RussianAccent:
    def __init__(self, dependency):
        from brofessor.infrastructure.speech.catalogue import installed_path

        path = installed_path(dependency)
        if path is None:
            raise SpeechError("Download Kokoro RU and its RUAccent resources first")
        self.model = _load_accent(path)

    def prepare(self, text, cancelled=None):
        _check(cancelled)
        # Preserve manual marks after a contextual pass over the whole sentence.
        clean = _plus(text).replace("+", "")
        result = preserve_text(text, self.model.process_all(clean))
        _check(cancelled)
        return result


class KokoroRU:
    def __init__(self, spec, location):
        from brofessor.infrastructure.speech._kokoro_ru_g2p import RuG2P

        self.spec, self.location = spec, location
        self.vocab = json.loads((location / "config.json").read_text())["vocab"]
        self.g2p = RuG2P(location, self.vocab)
        self.accent = RussianAccent(spec["dependencies"][0])
        self.sessions, self.styles = {}, {}

    def prepare_text(self, text, language, cancelled):
        return self.accent.prepare(text, cancelled)

    def synthesize(self, text, voice, language, cancelled):
        import numpy as np
        import onnxruntime as ort

        if language != ContentLanguage.RU or voice not in self.spec["available_voices"]:
            raise SpeechError("Kokoro RU requires Russian and an installed Russian voice")
        # Split at sentence/phrase boundaries, never truncate a 510-token input.
        chunks = re.split(r"(?<=[.!?;:])\s+", text.strip())
        audio = []
        checkpoint = "model_dima.onnx" if voice == "dima" else "model.onnx"
        if checkpoint not in self.sessions:
            options = ort.SessionOptions()
            options.intra_op_num_threads = 4
            self.sessions[checkpoint] = ort.InferenceSession(
                str(self.location / "onnx" / checkpoint),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
        if voice not in self.styles:
            self.styles[voice] = np.fromfile(
                self.location / "voices" / f"{voice}.bin", dtype=np.float32
            ).reshape(510, 256)
        for chunk in chunks:
            _check(cancelled)
            ipa = self.g2p.phonemize(chunk)
            missing = set(ipa) - self.vocab.keys()
            if missing:
                raise SpeechError(f"Kokoro RU cannot pronounce these phonemes: {sorted(missing)}")
            if not 1 <= len(ipa) <= 510:
                raise SpeechError("Kokoro RU phrase exceeds 510 phonemes; split this turn")
            ids = [self.vocab[c] for c in ipa]
            wave = self.sessions[checkpoint].run(
                None,
                {
                    "input_ids": np.array([[0, *ids, 0]], dtype=np.int64),
                    "style": self.styles[voice][len(ipa) - 1][None],
                    "speed": np.array([self.spec["settings"]["speed"]], dtype=np.float32),
                },
            )[0]
            _check(cancelled)
            if audio:
                audio.append(np.zeros(6000, dtype=np.float32))
            audio.append(wave.reshape(-1))
        return np.concatenate(audio), self.spec["settings"]["sample_rate"]
