"""Read-only directory collections. Connecting a path never reads its documents."""

import hashlib
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import yaml

from brofessor.contracts.content import UnitStatus
from brofessor.infrastructure.formats import ingestion as sources
from brofessor.infrastructure.formats.contracts import SOURCE_EXTENSIONS, DocumentExtension
from brofessor.infrastructure.storage.workspace import atomic_json

EXCLUDED = {".git", ".obsidian", ".trash", "__pycache__", ".venv", "node_modules"}
MAX_FILES = 100000
MAX_TOOL_CHARS = 22000
MAX_SEARCH_CHARS = 32 * 1024 * 1024


def connect(workspace, path):
    root = Path(path).expanduser().resolve()
    if not root.is_dir() or not os.access(root, os.R_OK | os.X_OK):
        raise ValueError("Choose a readable document directory")
    if root == workspace.path:
        raise ValueError("A document collection must be separate from its brofessor workspace")
    identifier = "dir-" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    with workspace.connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO collections VALUES (?,?,?)", (identifier, str(root), time.time())
        )
    return next(item for item in registered(workspace) if item["id"] == identifier)


def registered(workspace):
    with workspace.connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM collections ORDER BY created,id")]


def disconnect(workspace, identifier):
    with workspace.connect() as db:
        if not db.execute("DELETE FROM collections WHERE id=?", (identifier,)).rowcount:
            raise ValueError("Unknown document collection")


def choices(workspace):
    return [s for s in workspace.sources() if not s.get("hidden")] + [
        {**r, "name": Path(r["root"]).name + "/", "kind": "directory"}
        for r in registered(workspace)
    ]


def relative(value):
    value = unquote(value)
    if "\\" in value or "\x00" in value or PurePosixPath(value).is_absolute():
        raise ValueError("Use a path relative to the connected directory")
    parts = []
    for part in value.split("/"):
        if part == "..":
            if not parts:
                raise ValueError("Path escapes the connected directory")
            parts.pop()
        elif part not in ("", "."):
            parts.append(part)
    return "/".join(parts)


def markdown(text):
    """Extract navigation metadata only. No plugins, queries or code are run."""
    aliases, tags = [], []
    if text.startswith("---\n") or text.startswith("---\r\n"):
        match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
        if match and len(match[1]) <= 65536:
            try:
                # YAML aliases are unnecessary for note metadata and can expand
                # or cycle. Ignore unsupported frontmatter, keeping the original.
                if not any(
                    isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(match[1])
                ):
                    data = yaml.safe_load(match[1])
                    if isinstance(data, dict):

                        def strings(key):
                            value = data.get(key, [])
                            value = [value] if isinstance(value, str) else value
                            return (
                                [v for v in value[:128] if isinstance(v, str)]
                                if isinstance(value, list)
                                else []
                            )

                        aliases, tags = strings("aliases"), strings("tags")
            except (yaml.YAMLError, RecursionError):
                pass
    headings, links, visible = [], [], []
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        code = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if code:
            if fence is None:
                fence = code[1]
            elif (
                code[1][0] == fence[0]
                and len(code[1]) >= len(fence)
                and not line[code.end() :].strip()
            ):
                fence = None
            continue
        if fence:
            continue
        heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)(?:\s+#+)?\s*$", line)
        if heading:
            headings.append({"title": heading[2], "line": number, "level": len(heading[1])})
        clean = re.sub(r"`+[^`]*`+", "", line)
        visible.append(clean)
        for target in re.findall(r"!?\[\[([^\]\n]+)\]\]", clean):
            links.append({"target": target.split("|", 1)[0].replace("\\", ""), "syntax": "wiki"})
        for target in re.findall(r"!?\[[^\]\n]*\]\(([^)\n]+)\)", clean):
            links.append(
                {"target": target.strip().strip("<>").split(' "', 1)[0], "syntax": "markdown"}
            )
    tags.extend(re.findall(r"(?<!\w)#([\w/-]+)", "\n".join(visible)))
    return {
        "headings": headings,
        "aliases": aliases,
        "tags": sorted(set(tags)),
        "links": list({(v["target"], v["syntax"]): v for v in links}.values()),
    }


class Catalog:
    def __init__(self, workspace, roots, folder, *, check=lambda: None):
        self.workspace, self.roots, self.folder, self.check = (
            workspace,
            {r["id"]: r for r in roots},
            folder,
            check,
        )
        self.documents = {}
        self.issues = []
        manifest = folder / "catalog.json"
        if manifest.exists():
            saved = json.loads(manifest.read_text())
            self.documents = saved["documents"]
            self.issues = saved["issues"]
            return
        for identifier, root in self.roots.items():
            base = Path(root["root"])
            if not base.is_dir() or base.resolve() != base:
                raise ValueError(f"Connected directory is unavailable: {base}")

            def onerror(error):
                self.issues.append(
                    {
                        "collection_id": identifier,
                        "path": str(Path(error.filename).relative_to(base)),
                        "reason": "unreadable_directory",
                    }
                )

            for current, directories, filenames in os.walk(
                base, followlinks=False, onerror=onerror
            ):
                self.check()
                directories[:] = sorted(
                    d
                    for d in directories
                    if d not in EXCLUDED
                    and not d.startswith(".")
                    and not (Path(current) / d).is_symlink()
                    and (Path(current) / d).resolve() != workspace.path
                )
                for name in sorted(filenames):
                    path = Path(current) / name
                    rel = path.relative_to(base).as_posix()
                    if path.suffix.lower() not in SOURCE_EXTENSIONS or name.startswith("."):
                        continue
                    if path.is_symlink():
                        self.issues.append(
                            {
                                "collection_id": identifier,
                                "path": rel,
                                "reason": "symlink_not_followed",
                            }
                        )
                        continue
                    self.documents[identifier + ":" + rel] = {
                        "collection_id": identifier,
                        "path": rel,
                    }
                    if len(self.documents) > MAX_FILES:
                        raise ValueError(
                            "Directory exceeds the document limit; connect a narrower directory"
                        )
        atomic_json(manifest, {"documents": self.documents, "issues": self.issues})

    def key(self, collection_id, path):
        if collection_id not in self.roots:
            raise ValueError("Choose a connected collection ID")
        return collection_id + ":" + relative(path)

    def load(self, key):
        self.check()
        if key not in self.documents:
            raise ValueError("Document is not in this task's catalog")
        item = self.documents[key]
        cache = self.folder / "documents" / (hashlib.sha256(key.encode()).hexdigest() + ".json")
        if cache.exists():
            return json.loads(cache.read_text())
        base = Path(self.roots[item["collection_id"]]["root"])
        path = base / item["path"]
        if (
            base.resolve() != base
            or not path.resolve().is_relative_to(base)
            or any(
                (base / Path(*Path(item["path"]).parts[:i])).is_symlink()
                for i in range(1, len(Path(item["path"]).parts) + 1)
            )
        ):
            raise ValueError("Document path no longer belongs to the connected directory")
        if path.stat().st_size > sources.MAX_SOURCE_BYTES:
            raise ValueError("Document exceeds the source size limit")
        with path.open("rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Document is not a regular file")
            data = stream.read(sources.MAX_SOURCE_BYTES + 1)
        if len(data) > sources.MAX_SOURCE_BYTES:
            raise ValueError("Document exceeds the source size limit")
        # Import the bytes just read; reopening the changing vault is forbidden.
        with tempfile.TemporaryDirectory(dir=self.folder) as scratch:
            frozen = Path(scratch) / path.name
            frozen.write_bytes(data)
            source = self.workspace.add_source(frozen, name=item["path"], hidden=True)
        metadata = (
            markdown(data.decode("utf-8-sig"))
            if path.suffix.lower() == DocumentExtension.MARKDOWN
            else {"headings": [], "aliases": [], "tags": [], "links": []}
        )
        value = {
            **item,
            **metadata,
            "source_id": source["id"],
            "sha256": source["hash"],
            "units": self.workspace.units([source["id"]]),
        }
        atomic_json(cache, value)
        return value

    def listing(self, collection_id, path="", start=0, limit=40):
        prefix = relative(path).rstrip("/")
        prefix = prefix + "/" if prefix else ""
        entries = set()
        for item in self.documents.values():
            if item["collection_id"] == collection_id and item["path"].startswith(prefix):
                tail = item["path"][len(prefix) :]
                part = tail.split("/", 1)[0] + ("/" if "/" in tail else "")
                entries.add(prefix + part)
        ordered = sorted(entries)
        return {
            "entries": ordered[start : start + limit],
            "total": len(ordered),
            "next": start + limit if start + limit < len(ordered) else None,
        }

    def search(self, query, collection_id, path="", start=0, limit=8):
        candidates, lookup = [], {}
        characters = 0
        prefix = relative(path).rstrip("/")
        for key, item in self.documents.items():
            if item["collection_id"] != collection_id or (
                prefix and item["path"] != prefix and not item["path"].startswith(prefix + "/")
            ):
                continue
            try:
                doc = self.load(key)
            except (OSError, ValueError) as error:
                self.issues.append({**item, "reason": str(error)})
                continue
            for n, u in enumerate(doc["units"]):
                if u["status"] != UnitStatus.READY:
                    continue
                identifier = key + ":" + str(n)
                characters += (
                    len(u["text"]) + len(item["path"]) + sum(map(len, doc["aliases"] + doc["tags"]))
                )
                if characters > MAX_SEARCH_CHARS:
                    raise ValueError(
                        "Search scope exceeds the local text budget; search a narrower directory"
                    )
                candidates.append(
                    {
                        "id": identifier,
                        "status": UnitStatus.READY,
                        "text": item["path"]
                        + "\n"
                        + " ".join(doc["aliases"] + doc["tags"])
                        + "\n"
                        + u["text"],
                    }
                )
                lookup[identifier] = (doc, n, u)
        found = sources.search_units(candidates, query, limit=start + limit)
        rows = []
        for result in found[start:]:
            doc, n, u = lookup[result["id"]]
            rows.append(
                {
                    "path": doc["path"],
                    "start": n,
                    "locator": u["locator"],
                    "preview": u["text"][:700],
                    "headings": doc["headings"][:20],
                }
            )
        return {
            "matches": rows,
            "next": start + limit if len(found) == start + limit else None,
            "errors": self.issues[-10:],
        }

    def targets(self, document, target):
        syntax = target.get("syntax", "wiki") if isinstance(target, dict) else "wiki"
        target = target["target"] if isinstance(target, dict) else target
        uri = urlsplit(target)
        if uri.scheme or uri.netloc or uri.query:
            return {"target": target, "status": "external"}
        path, _, anchor = unquote(target).partition("#")
        try:
            rel = (
                relative(str(PurePosixPath(document["path"]).parent / path))
                if syntax == "markdown" and path
                else relative(path)
                if path
                else document["path"]
            )
        except ValueError:
            return {"target": target, "status": "outside_collection"}
        possibilities = {rel}
        possibilities |= {
            p + DocumentExtension.MARKDOWN for p in possibilities if not PurePosixPath(p).suffix
        }
        matches = [
            key
            for key, item in self.documents.items()
            if item["collection_id"] == document["collection_id"] and item["path"] in possibilities
        ]
        if syntax == "wiki" and "/" not in rel:
            matches = []
            for key, item in self.documents.items():
                if item["collection_id"] != document["collection_id"]:
                    continue
                if PurePosixPath(item["path"]).stem == PurePosixPath(rel).stem:
                    matches.append(key)
            if not matches:
                for key, item in self.documents.items():
                    if item["collection_id"] != document["collection_id"] or not item[
                        "path"
                    ].endswith(DocumentExtension.MARKDOWN):
                        continue
                    try:
                        if rel in self.load(key)["aliases"]:
                            matches.append(key)
                    except (OSError, ValueError):
                        continue
        return {
            "target": target,
            "anchor": anchor,
            "status": "resolved"
            if len(matches) == 1
            else "ambiguous"
            if matches
            else "missing_or_unsupported",
            "paths": [self.documents[k]["path"] for k in matches],
        }

    def links(self, collection_id, path, incoming=False):
        document = self.load(self.key(collection_id, path))
        outgoing = [self.targets(document, target) for target in document["links"]]
        backward = []
        if incoming:
            for key, item in self.documents.items():
                if item["collection_id"] != collection_id or not item["path"].endswith(
                    DocumentExtension.MARKDOWN
                ):
                    continue
                try:
                    other = self.load(key)
                except (OSError, ValueError):
                    continue
                targets = [self.targets(other, t) for t in other["links"]]
                if any(t["status"] == "resolved" and path in t.get("paths", []) for t in targets):
                    backward.append(item["path"])
        return {
            "outgoing": outgoing[:100],
            "incoming": backward[:100],
            "truncated": len(outgoing) > 100 or len(backward) > 100,
        }
