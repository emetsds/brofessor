"""Independent ZIP/XML/resource audit, separate from translation and EPUBCheck.

Usage: uv run python tools/check_epub_translation.py ORIGINAL.epub TRANSLATED.epub
This verifies preservation, not semantic translation quality.
"""

import argparse
import hashlib
import json
import posixpath
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

from brofessor.infrastructure.formats.epub import DC, NCX, XML_LANG, EpubBook
from brofessor.infrastructure.formats.epub_xml import publication_xml


def audit(source, translated):
    book = EpubBook(source)
    paths = [book.package_path, *book.document_paths, *book.navigation_paths]
    problems = []
    with ZipFile(translated) as archive:
        entries = {p: archive.read(p) for p in archive.namelist() if not p.endswith("/")}
    if set(entries) != set(book.entries):
        problems.append("Changed ZIP resource set")
    assets = set(book.entries) - set(paths)
    for path in assets:
        if entries.get(path) != book.entries[path]:
            problems.append(f"Changed resource: {path}")
    roots = {path: publication_xml(entries[path]) for path in paths}
    frozen_tags = {"pre", "code", "kbd", "samp", "math", "svg", "style", "script"}

    def compare(before, after, path, frozen=False):
        if before.tag != after.tag:
            problems.append(f"Changed element: {path}")
            return
        local = before.tag.rsplit("}", 1)[-1]
        frozen = (
            frozen
            or local in frozen_tags
            or before.get("translate") == "no"
            or (
                before.get("id") in {"pg-header", "pg-footer"}
                and "pg-boilerplate" in before.get("class", "").split()
            )
        )
        ignored = {"lang", XML_LANG}
        if not frozen:
            ignored.update({"alt", "title", "aria-label"})
        if before.tag == f"{{{NCX}}}meta" and before.get("name") == "dtb:uid":
            ignored.add("content")
        if {k: v for k, v in before.attrib.items() if k not in ignored} != {
            k: v for k, v in after.attrib.items() if k not in ignored
        }:
            problems.append(f"Changed immutable attributes: {path}")
        if frozen and "".join(before.itertext()) != "".join(after.itertext()):
            problems.append(f"Changed protected content: {path}")
        original, rendered = list(before), list(after)
        if local == "metadata" and rendered and rendered[-1].tag == f"{{{DC}}}source":
            rendered = rendered[:-1]
        if len(original) != len(rendered):
            problems.append(f"Changed child structure: {path}")
        for i, (a, b) in enumerate(zip(original, rendered)):
            compare(a, b, f"{path}/{i}", frozen)

    for path in paths:
        compare(publication_xml(book.entries[path]), roots[path], path)
    # Independent of the model projection/markers: compare literal function
    # spellings and arguments in the reconstructed XHTML, including frozen code.
    calls = re.compile(r"\b[A-Za-z_][A-Za-z_0-9]*\([^()\n]*\)")
    original_math, rendered_math = Counter(), Counter()
    for path in book.document_paths:
        original_math.update(
            re.sub(r"\s+", "", value)
            for value in calls.findall("".join(publication_xml(book.entries[path]).itertext()))
        )
        rendered_math.update(
            re.sub(r"\s+", "", value) for value in calls.findall("".join(roots[path].itertext()))
        )
    if original_math != rendered_math:
        problems.append("Changed plain-text mathematical/code function calls")
    # A separate value check, independent of the projection's lexical number
    # guard. Precision/sign spelling remain the core guard's responsibility.
    numerals = re.compile(r"[-−+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)")

    def numeric_values(root):
        return Counter(
            Decimal(v.replace(",", ".").replace("−", "-"))
            for v in numerals.findall("".join(root.itertext()))
        )

    numeric_count = 0
    for path in book.document_paths:
        original_values = numeric_values(publication_xml(book.entries[path]))
        numeric_count += sum(original_values.values())
        if original_values != numeric_values(roots[path]):
            problems.append(f"Changed XHTML numeric values: {path}")
    identifiers = {
        path: {e.get("id") for e in root.iter() if e.get("id")} for path, root in roots.items()
    }
    links, external = 0, 0
    for path, root in roots.items():
        for element in root.iter():
            for key in ("src", "href"):
                value = element.get(key)
                if not value:
                    continue
                uri = urlsplit(value)
                if uri.scheme or uri.netloc:
                    external += 1
                    continue
                links += 1
                destination = (
                    posixpath.normpath(str(PurePosixPath(path).parent / unquote(uri.path)))
                    if uri.path
                    else path
                )
                if (
                    destination not in entries
                    or uri.fragment
                    and unquote(uri.fragment) not in identifiers.get(destination, set())
                ):
                    problems.append(f"Broken internal link: {path} -> {value}")
    return {
        "source_sha256": book.source_hash,
        "output_sha256": hashlib.sha256(Path(translated).read_bytes()).hexdigest(),
        "epub_version": book.version,
        "text_blocks": len(book.blocks),
        "source_spine_documents": len(book.document_paths),
        "navigation_documents": len(book.navigation_paths),
        "plain_function_calls_checked": sum(original_math.values()),
        "numeric_values_checked": numeric_count,
        "unchanged_resources": len(assets),
        "asset_extensions": dict(Counter(Path(p).suffix for p in assets)),
        "internal_links_checked": links,
        "external_links_retained_without_fetching": external,
        "preserved_notices": book.preserved_notices,
        "problems": problems,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("translated", type=Path)
    args = parser.parse_args()
    result = audit(args.source, args.translated)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(bool(result["problems"]))
