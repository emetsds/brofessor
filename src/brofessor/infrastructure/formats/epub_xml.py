"""Offline publication XML, with bounded standard DTDs and namespace-safe editing.

Only known XHTML/NCX declarations are accepted. External subsets are never read;
XHTML's standard named characters are resolved locally, once. Source namespace
declarations (including bindings used only in QName-valued metadata) survive edits.
"""

import re
import xml.etree.ElementTree as ET
from html.entities import name2codepoint
from typing import Final
from xml.dom import Node, minidom

XML: Final = "http://www.w3.org/XML/1998/namespace"
XMLNS: Final = "http://www.w3.org/2000/xmlns/"
XHTML: Final = "http://www.w3.org/1999/xhtml"
OPF: Final = "http://www.idpf.org/2007/opf"
DC: Final = "http://purl.org/dc/elements/1.1/"
OPS: Final = "http://www.idpf.org/2007/ops"
NCX: Final = "http://www.daisy.org/z3986/2005/ncx/"
XML_LANG: Final = f"{{{XML}}}lang"
_DTDS = {
    ("html", "", ""),
    ("html", "-//W3C//DTD XHTML 1.1//EN", "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd"),
    (
        "html",
        "-//W3C//DTD XHTML 1.0 Strict//EN",
        "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd",
    ),
    (
        "html",
        "-//W3C//DTD XHTML 1.0 Transitional//EN",
        "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd",
    ),
    (
        "ncx",
        "-//NISO//DTD ncx 2005-1//EN",
        "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd",
    ),
}
_DOCTYPE = re.compile(
    r"<!DOCTYPE\s+(html|ncx)(?:\s+PUBLIC\s+(['\"])([^'\"]+)\2\s+(['\"])([^'\"]+)\4)?\s*>"
)
_OPAQUE = re.compile(r"(<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>)", re.S)


def _prepare(data):
    try:
        encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        text = data.decode(encoding)
    except UnicodeError as error:
        raise ValueError("EPUB XML must be UTF-8 or UTF-16") from error
    text = re.sub(r"^<\?xml\s+[^?]*\?>", "", text, count=1)
    if "<!ENTITY" in text.upper():
        raise ValueError("EPUB entity declarations are not supported")
    declarations = list(_DOCTYPE.finditer(text))
    if len(declarations) > 1:
        raise ValueError("Multiple EPUB DOCTYPE declarations")
    doctype = None
    if declarations:
        match = declarations[0]
        doctype = (match[1], match[3] or "", match[5] or "")
        if doctype not in _DTDS or text[: match.start()].strip():
            raise ValueError("Unsupported EPUB DOCTYPE")
        text = text[: match.start()] + text[match.end() :]
    if "<!DOCTYPE" in text.upper():
        raise ValueError("Unsupported EPUB DOCTYPE or internal subset")

    def character(match):
        name = match[1]
        return f"&#{name2codepoint[name]};" if name in name2codepoint else match[0]

    # Do not interpret entity-like text inside comments, CDATA or instructions.
    parts = _OPAQUE.split(text)
    if doctype and doctype[0] == "html":
        parts[::2] = [re.sub(r"&([A-Za-z][A-Za-z0-9]+);", character, p) for p in parts[::2]]
    return "".join(parts), doctype


def publication_xml(data):
    text, _ = _prepare(data)
    try:
        return ET.fromstring(text)
    except ET.ParseError as error:
        raise ValueError("Invalid EPUB publication XML") from error


def _expanded(node):
    return f"{{{node.namespaceURI}}}{node.localName}" if node.namespaceURI else node.nodeName


def serialize_publication(original, updated):
    """Apply an edited ET projection to its original DOM, retaining namespace scopes."""
    text, doctype = _prepare(original)
    document = minidom.parseString(text)

    def sync(node, element):
        if _expanded(node) != element.tag:
            raise ValueError("EPUB XML structure changed during translation")
        attributes = {_expanded(a): a for a in node.attributes.values() if a.namespaceURI != XMLNS}
        for key, attribute in attributes.items():
            if key not in element.attrib:
                node.removeAttributeNode(attribute)
        for key, value in element.attrib.items():
            if key in attributes:
                attributes[key].value = value
            elif key.startswith("{" + XML + "}"):
                node.setAttributeNS(XML, "xml:" + key.split("}", 1)[1], value)
            elif "}" not in key:
                node.setAttribute(key, value)
            else:
                raise ValueError("Unexpected new namespaced EPUB attribute")
        children = [c for c in node.childNodes if c.nodeType == Node.ELEMENT_NODE]
        if len(children) > len(element):
            raise ValueError("EPUB XML elements cannot be removed")
        for child in list(element)[len(children) :]:
            # The renderer may append dc:source; no model can add XML elements.
            if child.tag != f"{{{DC}}}source":
                raise ValueError("Unexpected new EPUB element")
            new = document.createElementNS(DC, "dc:source")
            new.setAttributeNS(XMLNS, "xmlns:dc", DC)
            node.appendChild(new)
            children.append(new)
        for child, projected in zip(children, element, strict=True):
            sync(child, projected)
        # ET merges text around comments/PIs. Retain those nodes while replacing
        # only the corresponding direct text/CDATA segment between child elements.
        segments, current = [], []
        for child in list(node.childNodes):
            if child.nodeType == Node.ELEMENT_NODE:
                segments.append((current, child))
                current = []
            else:
                current.append(child)
        segments.append((current, None))
        values = [element.text, *[child.tail for child in element]]
        for (segment, following), value in zip(segments, values, strict=True):
            textual = [
                c for c in segment if c.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE)
            ]
            if value:
                node.insertBefore(
                    document.createTextNode(value), textual[0] if textual else following
                )
            for old in textual:
                node.removeChild(old)

    sync(document.documentElement, updated)
    if doctype:
        declaration = document.implementation.createDocumentType(*doctype)
        document.insertBefore(declaration, document.documentElement)
    return document.toxml(encoding="utf-8")
