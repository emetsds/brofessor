"""PDF projection v2: baseline paragraphs, typographic decoding and inline runs.

Font aliases come from the document's own Encoding/ToUnicode correspondence.
Unknown private-use characters fail instead of being guessed from a font name.
"""

import re
import unicodedata
from dataclasses import dataclass, field, replace


def _glyph(name):
    base = str(name).lstrip("/").split(".")[0]
    digits = "zero one two three four five six seven eight nine".split()
    if base in digits:
        return str(digits.index(base))
    if all(len(part) == 1 and part.isascii() and part.isalpha() for part in base.split("_")):
        return "".join(base.split("_"))
    return {"hyphen": "-", "space": " ", "nbspace": " "}.get(base)


def font_aliases(page):
    result = {}
    fonts = page["/Resources"].get("/Font", {})
    for reference in (fonts.get_object() if hasattr(fonts, "get_object") else fonts).values():
        font = reference.get_object()
        encoding = font.get("/Encoding")
        encoding = encoding.get_object() if encoding else None
        if not isinstance(encoding, dict) or "/ToUnicode" not in font:
            continue
        names, code = {}, 0
        for value in encoding.get("/Differences", []):
            if isinstance(value, int):
                code = value
            else:
                names[code] = _glyph(value)
                code += 1
        cmap = font["/ToUnicode"].get_data().decode("ascii", errors="strict")
        pairs = []
        for body in re.findall(r"beginbfchar(.*?)endbfchar", cmap, re.S):
            pairs.extend(
                (int(a, 16), bytes.fromhex(b).decode("utf-16-be"))
                for a, b in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", body)
            )
        for body in re.findall(r"beginbfrange(.*?)endbfrange", cmap, re.S):
            for a, b, c in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", body
            ):
                start, end, target = int(a, 16), int(b, 16), int(c, 16)
                if end - start > 65535:
                    raise ValueError("PDF font character range exceeds the supported limit")
                pairs.extend((n, chr(target + n - start)) for n in range(start, end + 1))
        aliases = result.setdefault(str(font["/BaseFont"]).lstrip("/").split("+")[-1], {})
        for code, value in pairs:
            if len(value) == 1 and unicodedata.category(value) == "Co" and names.get(code):
                if value in aliases and aliases[value] != names[code]:
                    raise ValueError("Ambiguous private-use PDF font mapping")
                aliases[value] = names[code]
    return result


def decode(text, aliases):
    result = ""
    for char in text:
        if unicodedata.category(char) == "Co":
            if char not in aliases:
                raise ValueError(f"Unsupported private-use PDF glyph U+{ord(char):04X}")
            result += aliases[char]
        elif char == "\x02":
            result += "\u00ad"  # PDFium's inferred end-of-line discretionary hyphen.
        elif "\ufb00" <= char <= "\ufb06":
            result += unicodedata.normalize("NFKC", char)
        else:
            result += char
    return result


def union(boxes):
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


@dataclass
class Region:
    page: int
    spans: list
    bbox: tuple
    box: tuple | None = None
    text: str = ""
    protected: dict = field(default_factory=dict)
    runs: dict = field(default_factory=dict)
    frozen: str | None = None


def regions(spans, page, boundaries, width, height):
    license_page = any(
        s.text.strip() == "License" and s.size >= 14 for s in spans
    ) and "CreativeCommons" in "".join("".join(s.text.split()) for s in spans)
    aligned = []
    for span in spans:
        anchor = min(
            (
                other
                for other in spans
                if other.size > span.size * 1.25
                and 1 < span.baseline - other.baseline < other.size * 0.65
                and other.bbox[0] - other.size < span.bbox[0] < other.bbox[2] + other.size
            ),
            key=lambda other: abs(span.bbox[0] - other.bbox[2]),
            default=None,
        )
        aligned.append(replace(span, baseline=anchor.baseline, script=True) if anchor else span)
    spans = aligned
    lines = []
    for span in sorted(spans, key=lambda s: (-round(s.baseline, 1), s.bbox[0])):
        candidate = next(
            (
                line
                for line in reversed(lines)
                if abs(line.spans[0].baseline - span.baseline) < 0.7
                and -span.size * 0.4
                <= span.bbox[0] - line.bbox[2]
                < max(span.size, line.spans[0].size) * 1.8
                and not any(
                    abs(x0 - x1) < 0.2
                    and line.bbox[2] <= x0 <= span.bbox[0]
                    and min(y0, y1) < span.baseline < max(y0, y1)
                    for x0, y0, x1, y1 in boundaries
                )
            ),
            None,
        )
        if candidate is None:
            lines.append(Region(page, [span], span.bbox))
        else:
            candidate.spans.append(span)
            candidate.bbox = union([candidate.bbox, span.bbox])
    for line in lines:
        plain = "".join(s.text for s in line.spans).strip()
        if (
            line.spans[0].size >= 11
            and all(s.mono for s in line.spans)
            and not any(s.frozen == "code" for s in line.spans)
            and re.fullmatch(r"[A-Za-z][A-Za-z ,’'—-]+[.!?]", plain)
        ):
            line.spans = [replace(s, mono=False) for s in line.spans]
        if license_page:
            line.frozen = "license"
        elif all(s.mono for s in line.spans):
            line.frozen = "code"
        elif all(s.frozen for s in line.spans):
            line.frozen = line.spans[0].frozen
        elif re.fullmatch(r"[A-Z](?:['’])?", plain) or (
            (line.spans[0].size < 9 or all(s.form for s in line.spans))
            and re.fullmatch(r"[A-Z][A-Z ^'+()]+", plain)
        ):
            line.frozen = "diagram label"
        elif (line.bbox[1] > height * 0.85 or line.bbox[3] < height * 0.12) and (
            "©" in plain or "http" in plain
        ):
            line.frozen = "notice"
    combined = []
    for line in lines:
        previous = next(
            (
                r
                for r in reversed(combined)
                if not r.frozen
                and not line.frozen
                and not line.spans[0].text.lstrip().startswith("•")
                and abs(max(s.size for s in r.spans) - max(s.size for s in line.spans)) < 1
                and 0
                < r.spans[-1].baseline - line.spans[0].baseline
                <= max(s.size for s in line.spans) * 1.65
                and abs(r.bbox[0] - line.bbox[0]) <= line.spans[0].size * 2.5
                and not any(
                    abs(y0 - y1) < 0.2
                    and line.bbox[3] <= y0 <= r.bbox[1]
                    and min(x0, x1) < line.bbox[2]
                    and max(x0, x1) > line.bbox[0]
                    for x0, y0, x1, y1 in boundaries
                )
            ),
            None,
        )
        if previous is None:
            combined.append(line)
        else:
            previous.spans.extend(line.spans)
            previous.bbox = union([previous.bbox, line.bbox])
    for region in combined:
        # A repeated right-hand numeric column (contents/page references) fixes
        # row topology. Keep it explicit while allowing each label to translate.
        numeric_rows = [
            line
            for line in lines
            if line.frozen == "numeric/symbol"
            and line.bbox[0] > width * 0.7
            and re.fullmatch(r"\d+", line.text or "".join(s.text for s in line.spans).strip())
        ]
        table_rows = (
            sum(
                any(abs(s.baseline - n.spans[0].baseline) < 0.7 for s in region.spans)
                for n in numeric_rows
            )
            >= 4
        )
        region.row_baselines = (
            sorted({round(s.baseline, 2) for s in region.spans}, reverse=True) if table_rows else []
        )
        region.numbers = (
            [
                next(n for n in numeric_rows if abs(n.spans[0].baseline - baseline) < 0.7)
                for baseline in region.row_baselines
            ]
            if table_rows
            else []
        )
        parts, previous = [], None
        for span in region.spans:
            if previous:
                newline = previous.baseline - span.baseline > 1
                if newline and table_rows:
                    marker = f"⟦keep:{len(region.protected)}⟧"
                    region.protected[marker] = "\n"
                    region.runs[marker] = {"style": "break", "color": span.color}
                    parts.append(" " + marker)
                elif newline and previous.text.rstrip().endswith("\u00ad"):
                    if parts[-1] in region.protected:
                        region.protected[parts[-1]] = region.protected[parts[-1]].replace(
                            "\u00ad", ""
                        )
                    else:
                        parts[-1] = parts[-1].replace("\u00ad", "")
                elif (
                    previous.text.endswith(" ")
                    or span.text.startswith(" ")
                    or newline
                    or span.bbox[0] - previous.bbox[2] > span.size * 0.18
                ):
                    parts.append(" ")
            text = span.text.strip()
            if not region.frozen and (span.mono or span.script):
                marker = f"⟦keep:{len(region.protected)}⟧"
                region.protected[marker] = text
                region.runs[marker] = {
                    "style": "sup" if span.script else "code",
                    "color": span.color,
                }
                if (
                    previous
                    and previous.mono
                    and span.mono
                    and abs(previous.baseline - span.baseline) < 0.7
                    and not previous.text.endswith(" ")
                    and not span.text.startswith(" ")
                    and span.bbox[0] - previous.bbox[2] < span.size * 0.6
                ):
                    last = next((p for p in reversed(parts) if p.strip()), None)
                    if last in region.protected and region.runs[last]["style"] == "code":
                        region.protected[last] += text
                        region.protected[marker] = ""
                parts.append(marker)
            elif not region.frozen and (
                span.style != region.spans[0].style or span.color != region.spans[0].color
            ):
                n = len(region.runs)
                marker = f"⟦open:{n}⟧"
                region.runs[marker] = {"style": span.style, "color": span.color}
                parts.append(marker + text + f"⟦close:{n}⟧")
            else:
                parts.append(text)
            previous = span
        region.text = "".join(parts).replace("\u00ad", "-")
        region.protected = {k: v.replace("\u00ad", "-") for k, v in region.protected.items()}
        # Articles may disappear in Russian. Keep them in the adjacent styled
        # phrase so an otherwise complete translation need not invent an extra
        # word merely to fill an unstyled slot containing only "A" or "The".
        region.text = re.sub(r"\b([Aa]n? |[Tt]he )(⟦open:\d+⟧)", r"\2\1", region.text)
        # PDF exporters often draw one object per word. Adjacent equal styles
        # belong to one inline run, rather than imposing a marker on every word.
        while True:
            match = re.search(r"⟦close:(\d+)⟧(\s*)⟦open:(\d+)⟧", region.text)
            if match is None:
                break
            first, second = match[1], match[3]
            if region.runs[f"⟦open:{first}⟧"] != region.runs[f"⟦open:{second}⟧"]:
                break
            region.text = region.text[: match.start()] + match[2] + region.text[match.end() :]
            region.text = region.text.replace(f"⟦close:{second}⟧", f"⟦close:{first}⟧")
    for region in combined:
        region.following_code = [
            other
            for other in combined
            if not region.frozen
            and other.frozen == "code"
            and all(s.form for s in region.spans + other.spans)
            and 0 <= region.bbox[1] - other.bbox[3] < max(s.size for s in region.spans) * 1.5
            and region.bbox[0] <= (other.bbox[0] + other.bbox[2]) / 2 <= region.bbox[2]
        ]
    return combined
