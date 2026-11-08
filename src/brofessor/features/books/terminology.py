"""Contextual book terminology, grounded in exact original occurrences.

An entry is a meaning, not a global word replacement. Model-supplied quotes
resolve locally to source spans. Translation anchors keep corrections within
specific accepted phrases; manually edited phrases are retained explicitly.
"""

import difflib
import hashlib
import json
import re
from collections import Counter, defaultdict
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from brofessor import prompts
from brofessor.contracts.content import ContentLanguageValue
from brofessor.contracts.jobs import StageId
from brofessor.infrastructure.formats.epub import (
    MARKER,
    TranslationBatch,
    translation_prompt,
    validate_batch,
)
from brofessor.models import Output
from brofessor.prompts import ids as prompt_ids


class TermOrigin(StrEnum):
    AUTOMATIC = "automatic"
    USER = "user"


TermOriginValue = Literal[TermOrigin.AUTOMATIC, TermOrigin.USER]

PROMPT_BUDGET = 40000
_REVIEW_WORD = re.compile(r"[^\W\d_]+(?:[-’'][^\W\d_]+)*")
_FUNCTION_WORDS = set(
    "a an the and or but of to in on at by for from with without as is are was were be been "
    "being this that these those it its we you he she they our your their his her not no "
    "if then than so which who what when where how can may must should will would could "
    "have has had do does did done any all each both also same other some more most much "
    "very such thus now given following above below over under per first second next last one two three "
    "set read move use used using take find see multiply divide number numbers result results answer answers example examples "
    "и или но в на с со по из к у о об от до для при без как что это эти тот та то те "
    "он она они мы вы его её их наш ваш не ни если то чем где когда чтобы который "
    "которая которые было были будет быть есть может нужно можно все весь каждый "
    "так также уже ещё этого этой этих только после перед между через затем например".split()
)


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


def normal(text):
    return " ".join(text.casefold().split())


def identifier(*parts):
    return hashlib.sha256(encoded(parts).encode()).hexdigest()[:20]


class Seed(Output):
    term: str = Field(min_length=1, max_length=160)
    sense: str = Field(min_length=1, max_length=500)
    translation: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def meaningful_fields(self):
        for key in ("term", "sense", "translation"):
            value = getattr(self, key).strip()
            if not value:
                raise ValueError("Term, meaning and translation must not be blank")
            setattr(self, key, value)
        return self


class Term(Seed):
    id: str
    origin: TermOriginValue


class Mention(Output):
    quote: str = Field(min_length=1, max_length=3000)
    surface: str = Field(min_length=1, max_length=300)
    match: int = Field(ge=1, le=100)


class SourceMention(Mention):
    block_id: str


class Proposal(Seed):
    existing_id: str | None
    occurrences: list[SourceMention] = Field(min_length=1, max_length=200)


class GlossaryBatch(Output):
    assessed_blocks: list[str]
    terms: list[Proposal] = Field(max_length=80)


class GlossaryReviewBatch(GlossaryBatch):
    """Additional grounded meanings/mentions; existing choices remain immutable."""


class Occurrence(Output):
    id: str
    term_id: str
    block_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str
    surface: str


class TargetMention(Mention):
    occurrence_id: str


class AlignedBlock(Output):
    id: str
    text: str = Field(min_length=1)
    targets: list[TargetMention]


class AlignedBatch(Output):
    blocks: list[AlignedBlock] = Field(min_length=1)


class AlignmentBlock(Output):
    id: str
    targets: list[TargetMention]


class AlignmentBatch(Output):
    blocks: list[AlignmentBlock] = Field(min_length=1)


class Anchor(Output):
    occurrence_id: str
    start: int | None
    end: int | None
    manual: bool = False


class SavedBlock(Output):
    id: str
    text: str
    anchors: list[Anchor]


class Translation(Output):
    title: str
    language: ContentLanguageValue
    source_id: str
    source_sha256: str
    terms: list[Term]
    occurrences: list[Occurrence]
    blocks: list[SavedBlock]
    retained_manual: list[str] = Field(default_factory=list)


class Replacement(Output):
    occurrence_id: str
    text: str = Field(min_length=1, max_length=500)


class Replacements(Output):
    replacements: list[Replacement]


def seeds(value):
    terms = []
    seen = set()
    for item in value or []:
        seed = Seed.model_validate(item).model_dump()
        key = (normal(seed["term"]), normal(seed["sense"]))
        if key in seen:
            raise ValueError("User glossary repeats the same term and meaning")
        seen.add(key)
        terms.append({**seed, "id": identifier(*key), "origin": TermOrigin.USER})
    return terms


def locate(text, mention):
    """Resolve a unique exact quote, then its numbered exact surface occurrence."""
    quote, surface = mention["quote"], mention["surface"]
    quote_starts = [match.start() for match in re.finditer(re.escape(quote), text)]
    if len(quote_starts) != 1:
        raise ValueError("A terminology quote must occur exactly once in its block")
    matches = list(re.finditer(re.escape(surface), quote))
    index = mention["match"] - 1
    if index >= len(matches):
        raise ValueError("A terminology surface must occur in its exact quote")
    start = quote_starts[0] + matches[index].start()
    end = start + len(surface)
    if MARKER.search(text[start:end]):
        raise ValueError("A term must not cross protected inline markers")
    return start, end


def no_overlaps(spans):
    previous = 0
    for start, end in sorted(spans):
        if start < previous or end <= start:
            raise ValueError("Terminology occurrences must not overlap")
        previous = end


def merge_proposals(value, blocks, terms, occurrences, source_hash):
    by_block = {block.id: MARKER.sub("", block.text) for block in blocks}
    ids = value["assessed_blocks"]
    if len(ids) != len(by_block) or set(ids) != set(by_block):
        raise ValueError("Glossary extraction must assess every requested block exactly once")
    known = {term["id"]: dict(term) for term in terms}
    keys = {(normal(term["term"]), normal(term["sense"])): term["id"] for term in terms}
    additions = []
    spans = defaultdict(list)
    for occurrence in occurrences:
        spans[occurrence["block_id"]].append((occurrence["start"], occurrence["end"]))
    for proposal in value["terms"]:
        key = (normal(proposal["term"]), normal(proposal["sense"]))
        existing = proposal["existing_id"]
        if existing is not None:
            if existing not in known:
                raise ValueError("Unknown glossary meaning ID")
            term = known[existing]
            if any(proposal[field] != term[field] for field in ("term", "sense", "translation")):
                raise ValueError("Extraction must not rewrite an accepted glossary meaning")
        else:
            existing = keys.get(key)
            if existing is not None:
                term = known[existing]
                if proposal["translation"] != term["translation"]:
                    raise ValueError("Conflicting translations for the same glossary meaning")
            else:
                existing = identifier(*key)
                term = {field: proposal[field] for field in ("term", "sense", "translation")}
                term.update(id=existing, origin=TermOrigin.AUTOMATIC)
                known[existing], keys[key] = term, existing
        for mention in proposal["occurrences"]:
            block_id = mention["block_id"]
            if block_id not in by_block:
                raise ValueError("Terminology occurrence points outside its source packet")
            start, end = locate(by_block[block_id], mention)
            spans[block_id].append((start, end))
            additions.append(
                {
                    "id": identifier(source_hash, block_id, start, end, existing),
                    "term_id": existing,
                    "block_id": block_id,
                    "start": start,
                    "end": end,
                    "quote": mention["quote"],
                    "surface": mention["surface"],
                }
            )
    for values in spans.values():
        no_overlaps(values)
    return list(known.values()), [*occurrences, *additions]


def packets(blocks, prompt):
    """Bound the actual prompt, including glossary/context, without clipping a block."""
    current = []
    for block in blocks:
        candidate = [*current, block]
        if len(prompt(candidate)) <= PROMPT_BUDGET:
            current = candidate
            continue
        if current:
            yield current
        current = [block]
        if len(prompt(current)) > PROMPT_BUDGET:
            raise ValueError("A translation block and its context exceed the prompt budget")
    if current:
        yield current


def relevant_terms(blocks, terms, occurrences):
    text = normal("\n".join(MARKER.sub("", block.text) for block in blocks))
    aliases = defaultdict(set)
    for occurrence in occurrences:
        aliases[occurrence["term_id"]].add(normal(occurrence["surface"]))
    return [
        term
        for term in terms
        if any(phrase in text for phrase in {normal(term["term"]), *aliases[term["id"]]})
    ]


def discover(book, user_glossary, language, generate, check, progress):
    terms, occurrences = seeds(user_glossary), []

    def prompt(blocks):
        return prompts.render(
            "books/glossary",
            language=language,
            payload=encoded(
                {
                    "source_language": book.language,
                    "target_language": language,
                    "known_meanings": relevant_terms(blocks, terms, occurrences),
                    "blocks": [
                        {"id": block.id, "text": MARKER.sub("", block.text)} for block in blocks
                    ],
                }
            ),
        )

    completed = 0
    for batch in packets(book.blocks, prompt):
        check()
        text = prompt(batch)
        # The preceding packet may have added glossary entries after the generator
        # yielded. Check the complete current prompt again before any model call.
        if len(text) > PROMPT_BUDGET:
            raise ValueError("The accepted glossary exceeds the extraction packet budget")
        value = generate(
            text,
            GlossaryBatch,
            validate=lambda value: merge_proposals(
                value, batch, terms, occurrences, book.source_hash
            ),
        )
        terms, occurrences = merge_proposals(value, batch, terms, occurrences, book.source_hash)
        completed += len(batch)
        progress({"stage": StageId.GLOSSARY, "completed": completed, "total": len(book.blocks)})
    return terms, occurrences


def recurring_candidates(book, terms, occurrences):
    """Find repeated, unlisted surfaces for model review, without assigning meanings.

    Sampling bounds inference cost. It does not claim exhaustive terminology or
    automatically attach every spelling match to the same sense.
    """
    covered = {normal(t["term"]) for t in terms} | {normal(o["surface"]) for o in occurrences}
    counts, locations = Counter(), defaultdict(list)
    for block in book.blocks:
        text = MARKER.sub("", block.text)
        words = list(_REVIEW_WORD.finditer(text))
        found = set()
        for start in range(len(words)):
            for length in (1, 2, 3):
                group = words[start : start + length]
                if len(group) != length or any(
                    normal(w[0]) in _FUNCTION_WORDS
                    or len(w[0]) < 3
                    and not (len(w[0]) == 1 and w[0].isupper())
                    for w in group
                ):
                    continue
                if any(not text[a.end() : b.start()].isspace() for a, b in zip(group, group[1:])):
                    continue
                phrase = normal(text[group[0].start() : group[-1].end()])
                if phrase not in covered and (length > 1 or len(phrase) >= 3):
                    found.add(phrase)
        counts.update(found)
        for phrase in found:
            locations[phrase].append(block.id)
    selected = sorted((p for p in counts if counts[p] >= 3), key=lambda p: (-counts[p], p))[:32]
    return [
        {
            "surface": p,
            "blocks": counts[p],
            "examples": list(
                dict.fromkeys(
                    locations[p][i] for i in (0, len(locations[p]) // 2, len(locations[p]) - 1)
                )
            ),
        }
        for p in selected
    ]


def review_recurring(book, terms, occurrences, language, generate, check, progress):
    candidates = recurring_candidates(book, terms, occurrences)
    ids = {identifier for item in candidates for identifier in item["examples"]}
    blocks = [b for b in book.blocks if b.id in ids]

    def prompt(batch):
        batch_ids = {b.id for b in batch}
        return prompts.render(
            "books/review_glossary",
            payload=encoded(
                {
                    "source_language": book.language,
                    "target_language": language,
                    "candidates": [c for c in candidates if batch_ids.intersection(c["examples"])],
                    "known_meanings": relevant_terms(batch, terms, occurrences),
                    "blocks": [
                        {
                            "id": b.id,
                            "text": MARKER.sub("", b.text),
                            "occupied": [
                                {k: o[k] for k in ("start", "end", "surface", "term_id")}
                                for o in occurrences
                                if o["block_id"] == b.id
                            ],
                        }
                        for b in batch
                    ],
                }
            ),
        )

    completed = 0
    for batch in packets(blocks, prompt):
        check()
        text = prompt(batch)
        if len(text) > PROMPT_BUDGET:
            raise ValueError("The accepted glossary exceeds the review packet budget")
        value = generate(
            text,
            GlossaryReviewBatch,
            validate=lambda v: merge_proposals(v, batch, terms, occurrences, book.source_hash),
        )
        terms, occurrences = merge_proposals(value, batch, terms, occurrences, book.source_hash)
        completed += len(batch)
        progress({"stage": StageId.GLOSSARY_REVIEW, "completed": completed, "total": len(blocks)})
    return terms, occurrences


def aligned_blocks(value, blocks, occurrences):
    validate_batch(
        {"blocks": [{"id": item["id"], "text": item["text"]} for item in value["blocks"]]}, blocks
    )
    expected = {
        block.id: [item for item in occurrences if item["block_id"] == block.id] for block in blocks
    }
    result = []
    for item in value["blocks"]:
        ids = [target["occurrence_id"] for target in item["targets"]]
        if len(ids) != len(expected[item["id"]]) or set(ids) != {
            o["id"] for o in expected[item["id"]]
        }:
            raise ValueError(
                "Translation must align every requested terminology occurrence exactly once"
            )
        anchors = []
        for target in item["targets"]:
            start, end = locate(item["text"], target)
            anchors.append(
                {
                    "occurrence_id": target["occurrence_id"],
                    "start": start,
                    "end": end,
                    "manual": False,
                }
            )
        no_overlaps([(anchor["start"], anchor["end"]) for anchor in anchors])
        result.append({"id": item["id"], "text": item["text"], "anchors": anchors})
    return result


def validate_or_repair_alignment(value, blocks, terms, occurrences, generate):
    """Repair only rejected link hints, once, without changing translated text.

    Numbers/coverage/inline structure are checked before any repair. Correct
    blocks are retained. Neither the repair schema nor the merge accepts prose.
    The outer model checkpoint is accepted only after every link validates.
    """
    validate_batch(
        {"blocks": [{"id": b["id"], "text": b["text"]} for b in value["blocks"]]}, blocks
    )
    source = {b.id: b for b in blocks}
    rejected = {}
    for block in value["blocks"]:
        try:
            aligned_blocks({"blocks": [block]}, [source[block["id"]]], occurrences)
        except ValueError as error:
            rejected[block["id"]] = str(error)
    if not rejected:
        return aligned_blocks(value, blocks, occurrences)
    originals = {b["id"]: b for b in value["blocks"] if b["id"] in rejected}
    requested = [source[identifier] for identifier in originals]

    def apply(links):
        replacements = {b["id"]: b["targets"] for b in links["blocks"]}
        if len(replacements) != len(links["blocks"]) or set(replacements) != set(originals):
            raise ValueError("Alignment repair must cover exactly the rejected blocks")
        repaired = [
            {"id": identifier, "text": b["text"], "targets": replacements[identifier]}
            for identifier, b in originals.items()
        ]
        aligned_blocks({"blocks": repaired}, requested, occurrences)
        return replacements

    relevant = {o["term_id"] for o in occurrences if o["block_id"] in rejected}
    prompt = prompts.render(
        prompt_ids.BOOKS_REPAIR_ALIGNMENT,
        payload=encoded(
            {
                "glossary": [t for t in terms if t["id"] in relevant],
                "blocks": [
                    {
                        "id": identifier,
                        "source": source[identifier].as_dict(),
                        "text": b["text"],
                        "rejected_targets": b["targets"],
                        "error": rejected[identifier],
                        "occurrences": [o for o in occurrences if o["block_id"] == identifier],
                    }
                    for identifier, b in originals.items()
                ],
            }
        ),
    )
    if len(prompt) > PROMPT_BUDGET:
        raise ValueError("Rejected alignment and its context exceed the repair prompt budget")
    links = generate(prompt, AlignmentBatch, validate=apply)
    replacements = apply(links)
    for block in value["blocks"]:
        if block["id"] in replacements:
            block["targets"] = replacements[block["id"]]
    return aligned_blocks(value, blocks, occurrences)


def translate(book, terms, occurrences, language, generate, check, progress):
    def prompt(blocks):
        ids = {block.id for block in blocks}
        mentions = [item for item in occurrences if item["block_id"] in ids]
        term_ids = {item["term_id"] for item in mentions}
        glossary = [term for term in terms if term["id"] in term_ids]
        # A meaning discovered in a later packet can also apply to earlier blocks.
        relevant = {term["id"] for term in relevant_terms(blocks, terms, occurrences)}
        glossary = [term for term in terms if term["id"] in term_ids | relevant]
        metalinguistic = prompts.render(prompt_ids.BOOKS_METALINGUISTIC)
        return prompts.render(
            prompt_ids.BOOKS_ALIGN_TRANSLATION,
            translation=translation_prompt(blocks, language, glossary),
            metalinguistic=metalinguistic,
            occurrences=encoded({"occurrences": mentions}),
        )

    result = []
    for batch in packets(book.blocks, prompt):
        check()

        def validate(value):
            return validate_or_repair_alignment(value, batch, terms, occurrences, generate)

        value = generate(
            prompt(batch),
            AlignedBatch,
            validate=validate,
        )
        result.extend(aligned_blocks(value, batch, occurrences))
        progress(
            {"stage": StageId.TRANSLATION, "completed": len(result), "total": len(book.blocks)}
        )
    return result


def edit_blocks(state, texts):
    """Rebase unchanged anchors; a human change to a term locks that occurrence."""
    result = Translation.model_validate(state).model_dump()
    if set(texts) != {block["id"] for block in result["blocks"]}:
        raise ValueError("Editing must retain every original translation block")
    for block in result["blocks"]:
        old, new = block["text"], texts[block["id"]]
        if old == new:
            continue
        equal = [
            op
            for op in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
            if op[0] == "equal"
        ]
        for anchor in block["anchors"]:
            if anchor["manual"]:
                continue
            matching = next(
                (op for op in equal if op[1] <= anchor["start"] and anchor["end"] <= op[2]), None
            )
            if matching is None:
                anchor.update(start=None, end=None, manual=True)
            else:
                shift = matching[3] - matching[1]
                anchor.update(start=anchor["start"] + shift, end=anchor["end"] + shift)
        block["text"] = new
    return result


def revise(state, book, term_id, target, generate, check, progress):
    result = Translation.model_validate(state).model_dump()
    term = next((term for term in result["terms"] if term["id"] == term_id), None)
    if term is None:
        raise ValueError("Unknown glossary meaning")
    target = Seed(term=term["term"], sense=term["sense"], translation=target).translation
    term["translation"], term["origin"] = target, TermOrigin.USER
    occurrences = {o["id"]: o for o in result["occurrences"] if o["term_id"] == term_id}
    originals = {block.id: block for block in book.blocks}
    retained = []
    pending = {}
    for block in result["blocks"]:
        for anchor in block["anchors"]:
            if anchor["occurrence_id"] not in occurrences:
                continue
            if anchor["manual"]:
                retained.append(anchor["occurrence_id"])
            else:
                pending[anchor["occurrence_id"]] = (block, anchor)
    by_block = list(dict.fromkeys(block["id"] for block, _ in pending.values()))

    def prompt(blocks):
        ids = {block.id for block in blocks}
        return prompts.render(
            prompt_ids.BOOKS_REVISE_TERM,
            payload=encoded(
                {
                    "meaning": term,
                    "language": result["language"],
                    "blocks": [
                        {"id": block.id, "original": MARKER.sub("", block.text)} for block in blocks
                    ],
                    "occurrences": [
                        {
                            **occurrences[key],
                            "translated_context": block["text"],
                            "current_phrase": block["text"][anchor["start"] : anchor["end"]],
                        }
                        for key, (block, anchor) in pending.items()
                        if block["id"] in ids
                    ],
                }
            ),
        )

    replacements = {}
    for batch in packets([originals[key] for key in by_block], prompt):
        check()
        ids = {block.id for block in batch}
        expected = {key for key, (block, _) in pending.items() if block["id"] in ids}

        def validate(value):
            actual = [item["occurrence_id"] for item in value["replacements"]]
            if len(actual) != len(expected) or set(actual) != expected:
                raise ValueError("Term correction must cover exactly its editable occurrences")
            for item in value["replacements"]:
                if not item["text"].strip() or "⟦" in item["text"] or "⟧" in item["text"]:
                    raise ValueError("A replacement must be a nonempty term phrase without markers")

        value = generate(prompt(batch), Replacements, validate=validate)
        replacements.update({item["occurrence_id"]: item["text"] for item in value["replacements"]})
        progress(
            {
                "stage": StageId.TERMINOLOGY_UPDATE,
                "completed": len(replacements),
                "total": len(pending),
            }
        )
    for block in result["blocks"]:
        text, shift = block["text"], 0
        pieces, previous = [], 0
        for anchor in sorted(
            (a for a in block["anchors"] if not a["manual"]), key=lambda a: a["start"]
        ):
            start, end = anchor["start"], anchor["end"]
            new = replacements.get(anchor["occurrence_id"], text[start:end])
            pieces.extend((text[previous:start], new))
            anchor.update(start=start + shift, end=start + shift + len(new))
            shift += len(new) - (end - start)
            previous = end
        pieces.append(text[previous:])
        block["text"] = "".join(pieces)
    result["retained_manual"] = retained
    validate_batch(
        {"blocks": [{"id": block["id"], "text": block["text"]} for block in result["blocks"]]},
        book.blocks,
    )
    return result


def render_value(state):
    return TranslationBatch(
        blocks=[{"id": block["id"], "text": block["text"]} for block in state["blocks"]]
    ).model_dump()
