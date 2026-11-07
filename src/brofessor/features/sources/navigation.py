"""Bounded source navigation through the existing text adapters and worker.

The model selects typed retrieval actions; only this application executes them.
Every accepted observation and original fragment is durable before the next turn.
"""

import json
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final, Literal

from pydantic import Field, model_validator

from brofessor import prompts
from brofessor.contracts.content import ArtifactKind, UnitStatus
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.features.sources import collections, reading
from brofessor.infrastructure.storage.workspace import JOBS_DIRECTORY, atomic_json
from brofessor.models import Output

NAVIGATION_FILENAME: Final = "navigation.json"

MAX_STEPS = 24
MAX_CONTEXT = 48000
MAX_SELECTED = 80000


class NavigationOperation(StrEnum):
    LIST = "list"
    SEARCH = "search"
    READ = "read"
    LINKS = "links"
    FINISH = "finish"


NavigationOperationValue = Literal[
    NavigationOperation.LIST,
    NavigationOperation.SEARCH,
    NavigationOperation.READ,
    NavigationOperation.LINKS,
    NavigationOperation.FINISH,
]


class NavigationAction(Output):
    operation: NavigationOperationValue
    collection_id: str = ""
    path: str = ""
    query: str = ""
    section: str = ""
    start: int = Field(default=0, ge=0)
    limit: int = Field(default=4, ge=1, le=50)
    incoming: bool = False


class NavigationStep(Output):
    memory: str = Field(default="", max_length=1500)
    exhaustive: bool = False
    scope: list[str] = Field(default_factory=list, max_length=16)
    actions: list[NavigationAction] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def finish_alone(self):
        if len(self.actions) > 1 and any(
            action.operation == NavigationOperation.FINISH for action in self.actions
        ):
            raise ValueError("Finish must be the only navigation action")
        return self


def report(workspace, job):
    reference = job["params"].get("source_snapshot_job", job["id"])
    path = workspace.path / JOBS_DIRECTORY / reference / NAVIGATION_FILENAME
    return json.loads(path.read_text()) if path.is_file() else None


def source_ids(workspace, job):
    value = (
        report(workspace, job)
        if job["params"].get("collections") or job["params"].get("source_snapshot_job")
        else None
    )
    return list(
        dict.fromkeys(
            [*job["params"].get("source_ids", []), *(value.get("source_ids", []) if value else [])]
        )
    )


def units(workspace, job):
    value = (
        report(workspace, job)
        if job["params"].get("collections") or job["params"].get("source_snapshot_job")
        else None
    )
    regular = workspace.units(job["params"].get("source_ids", []))
    return list(
        {u["id"]: u for u in [*regular, *(value["units"].values() if value else [])]}.values()
    )


def names(workspace, job):
    result = {s["id"]: s["name"] for s in workspace.sources()}
    value = report(workspace, job)
    if value:
        paths = {}
        for item in value["documents"].values():
            paths.setdefault(item["source_id"], []).append(
                item["collection_name"] + "/" + item["path"]
            )
        result.update({key: " | ".join(sorted(set(values))) for key, values in paths.items()})
    return result


class NavigationSession:
    """Document operations and durable evidence, independent of the agent loop."""

    def __init__(self, workspace, job, check, progress, *, conversation=None):
        self.workspace, self.job = workspace, job
        self.check, self.progress = check, progress
        self.conversation = conversation
        self.folder = workspace.path / JOBS_DIRECTORY / job["id"]
        self.state_path = self.folder / NAVIGATION_FILENAME
        self.state = (
            json.loads(self.state_path.read_text())
            if self.state_path.exists()
            else {
                "status": JobStatus.RUNNING,
                "documents": {},
                "units": {},
                "source_ids": [],
                "steps": [],
                "issues": [],
            }
        )
        if self.state["status"] == "complete":
            return
        self.catalog = collections.Catalog(
            workspace, job["params"]["collections"], self.folder, check=check
        )
        self.roots = [
            {"id": r["id"], "name": PurePosixPath(r["root"]).name}
            for r in self.catalog.roots.values()
        ]

    def read(self, action):
        key = self.catalog.key(action["collection_id"], action["path"])
        document = self.catalog.load(key)
        units = document["units"]
        indexes = list(range(len(units)))
        if action["section"]:
            heading = action["section"].lstrip("#")
            headings = document["headings"]
            if heading.startswith("^"):
                # Block references retain their source line locator.
                candidates = [i for i, u in enumerate(units) if re_block(heading[1:], u["text"])]
                indexes = candidates
            else:
                matches = [
                    (n, h)
                    for n, h in enumerate(headings)
                    if h["title"].casefold() == heading.casefold()
                ]
                if len(matches) != 1:
                    raise ValueError(prompts.render("navigation/heading_hint"))
                n, h = matches[0]
                end = next(
                    (other["line"] for other in headings[n + 1 :] if other["level"] <= h["level"]),
                    float("inf"),
                )
                import re

                indexes = []
                for i, u in enumerate(units):
                    loc = re.match(r"lines (\d+)-(\d+)", u["locator"])
                    if loc and int(loc[2]) >= h["line"] and int(loc[1]) < end:
                        indexes.append(i)
            if not indexes:
                raise ValueError("No readable original fragment for this section")
        fragments = []
        selected = self.state["units"].copy()
        headings = document["headings"][:20]
        cursor = action["start"]
        while cursor < len(indexes) and len(fragments) < action["limit"]:
            unit = units[indexes[cursor]]
            if unit["status"] != UnitStatus.READY:
                cursor += 1
                continue
            candidate = [*fragments, {**unit, "source": document["path"]}]
            if (
                len(
                    reading.encoded(
                        {
                            "fragments": candidate,
                            "headings": headings,
                            "next": cursor + 1,
                            "total_fragments": len(indexes),
                        }
                    )
                )
                > collections.MAX_TOOL_CHARS
            ):
                break
            selected = {**selected, unit["id"]: unit}
            if len(reading.encoded(list(selected.values()))) > MAX_SELECTED:
                raise ValueError(prompts.render("navigation/selection_hint"))
            fragments = candidate
            cursor += 1
        self.state["units"] = selected
        self.state["source_ids"] = list(
            dict.fromkeys(u["source_id"] for u in self.state["units"].values())
        )
        if fragments:
            self.state["documents"][key] = {
                k: document[k] for k in ("collection_id", "path", "source_id", "sha256")
            }
            self.state["documents"][key]["collection_name"] = PurePosixPath(
                self.catalog.roots[document["collection_id"]]["root"]
            ).name
        return {
            "fragments": fragments,
            "headings": headings,
            "next": cursor if cursor < len(indexes) else None,
            "total_fragments": len(indexes),
        }

    def context(self):
        return {
            "task": self.job["params"]["focus"],
            "output": self.job["kind"],
            **(
                {"template": self.job["params"]["template"]}
                if self.job["kind"] == JobKind.REPORT
                else {}
            ),
            "roots": self.roots,
            "root_listing": {r["id"]: self.catalog.listing(r["id"], limit=20) for r in self.roots},
            "conversation": self.conversation or [],
        }

    def save(self):
        atomic_json(self.state_path, self.state)

    def apply(self, plan, *, operation_id):
        self.check()
        replay = self.state.setdefault("tool_results", {})
        if operation_id in replay:
            return replay[operation_id]
        if len(self.state["steps"]) >= MAX_STEPS:
            raise ValueError("Source navigation reached its step limit; progress is saved")

        def save(result):
            replay[operation_id] = result
            self.save()
            return result

        if plan["exhaustive"]:
            self.state["exhaustive"] = True
            self.state["scope"] = (
                plan["scope"] or self.state.get("scope") or [r["id"] + ":" for r in self.roots]
            )
        if any(a["operation"] == NavigationOperation.FINISH for a in plan["actions"]):
            candidates = [
                {"collection_id": observation["action"]["collection_id"], "path": match["path"]}
                for step in self.state["steps"]
                for observation in step
                for match in observation["result"].get("matches", [])
            ]
            attempted_read = any(
                observation["action"]["operation"] == NavigationOperation.READ
                for step in self.state["steps"]
                for observation in step
            )
            if candidates and not attempted_read and not self.state["units"]:
                self.state["steps"].append(
                    [
                        {
                            "action": plan["actions"][0],
                            "result": {
                                "error": prompts.render("navigation/read_candidates"),
                                "candidates": candidates[:6],
                            },
                        }
                    ]
                )
                return save(self.state["steps"][-1])
            missing = []
            if self.state.get("exhaustive"):
                keys = set()
                for scope in self.state["scope"]:
                    identifier, sep, prefix = scope.partition(":")
                    if not sep:
                        raise ValueError("Full-reading scope must include collection_id:path")
                    self.catalog.key(identifier, prefix)
                    prefix = collections.relative(prefix).rstrip("/")
                    if any(
                        issue["collection_id"] == identifier
                        and issue["reason"] == "unreadable_directory"
                        and (
                            not prefix
                            or issue["path"] in ("", ".")
                            or issue["path"] == prefix
                            or issue["path"].startswith(prefix + "/")
                            or prefix.startswith(issue["path"] + "/")
                        )
                        for issue in self.catalog.issues
                    ):
                        self.state["issues"] = self.catalog.issues
                        self.save()
                        raise ValueError(
                            "Full reading cannot cover an unreadable directory; see navigation report"
                        )
                    keys.update(
                        key
                        for key, item in self.catalog.documents.items()
                        if item["collection_id"] == identifier
                        and (
                            not prefix
                            or item["path"] == prefix
                            or item["path"].startswith(prefix + "/")
                        )
                    )
                verified_units = set()
                for key in sorted(keys):
                    try:
                        document = self.catalog.load(key)
                    except (OSError, ValueError) as error:
                        self.state["issues"] = [
                            *self.catalog.issues,
                            {**self.catalog.documents[key], "reason": str(error)},
                        ]
                        self.save()
                        raise ValueError(
                            "Full reading cannot cover an unavailable document; see navigation report"
                        ) from error
                    verified_units.update(
                        u["id"] for u in document["units"] if u["status"] == UnitStatus.READY
                    )
                    unread = [
                        i
                        for i, u in enumerate(document["units"])
                        if u["status"] == UnitStatus.READY
                        and (
                            key not in self.state["documents"] or u["id"] not in self.state["units"]
                        )
                    ]
                    if unread:
                        missing.append(
                            {
                                "collection_id": document["collection_id"],
                                "path": document["path"],
                                "start": unread[0],
                            }
                        )
                if missing:
                    self.state["steps"].append(
                        [
                            {
                                "action": plan["actions"][0],
                                "result": {
                                    "error": prompts.render("navigation/read_scope"),
                                    "unread": missing[:30],
                                    "total_unread_documents": len(missing),
                                },
                            }
                        ]
                    )
                    return save(self.state["steps"][-1])
                self.state["verification"] = {
                    "exhaustive": True,
                    "scope": self.state["scope"],
                    "documents": len(keys),
                    "fragments": len(verified_units),
                    "basis": "All extractable text fragments in the requested task catalog were read. "
                    "Hidden/system directories, symlinks and unsupported formats are excluded; "
                    "image-only content is not covered. Membership was captured at task start, "
                    "each document's bytes at first inspection.",
                }
            self.state.update(status="complete", issues=self.catalog.issues)
            result = save({"status": "complete"})
            self.workspace.add_artifact(
                self.job["id"], self.state_path, ArtifactKind.JSON, {"role": "source_navigation"}
            )
            return result
        observations = []
        for action in plan["actions"]:
            self.check()
            try:
                if action["operation"] == NavigationOperation.LIST:
                    self.catalog.key(action["collection_id"], action["path"])
                    result = self.catalog.listing(
                        action["collection_id"], action["path"], action["start"], action["limit"]
                    )
                elif action["operation"] == NavigationOperation.SEARCH:
                    self.catalog.key(action["collection_id"], action["path"])
                    if not action["query"].strip():
                        raise ValueError("A search query is required")
                    result = self.catalog.search(
                        action["query"],
                        action["collection_id"],
                        action["path"],
                        action["start"],
                        min(8, action["limit"]),
                    )
                elif action["operation"] == NavigationOperation.READ:
                    result = self.read(action)
                else:
                    result = self.catalog.links(
                        action["collection_id"], action["path"], action["incoming"]
                    )
            except (OSError, ValueError) as error:
                result = {"error": str(error)}
            # Whole fragments are bounded before inclusion. Metadata-only lists
            # can be long; make truncation explicit rather than truncating JSON.
            if len(reading.encoded(result)) > collections.MAX_TOOL_CHARS:
                result = {"error": prompts.render("navigation/narrow_tool")}
            observations.append({"action": action, "result": result})
        self.state["steps"].append(observations)
        self.state["issues"] = self.catalog.issues
        return save(observations)


def prepare(workspace, job, generate, check, progress, *, conversation=None):
    from brofessor.infrastructure.agents.navigation import run

    session = NavigationSession(workspace, job, check, progress, conversation=conversation)
    if session.state["status"] == "complete":
        workspace.add_artifact(
            job["id"], session.state_path, ArtifactKind.JSON, {"role": "source_navigation"}
        )
        return session.state
    return run(session, generate)


def re_block(identifier, text):
    import re

    return bool(re.search(r"\^" + re.escape(identifier) + r"(?:\s|$)", text))
