"""A directory of files and a small transactional SQLite database."""

import hashlib
import json
import os
import sqlite3
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Workspace:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError(f"Unsupported workspace schema {version}")
            if version == 1:
                return
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, hash TEXT UNIQUE NOT NULL,
                    original TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS units (
                    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
                    locator TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, params TEXT NOT NULL,
                    request_key TEXT UNIQUE NOT NULL, status TEXT NOT NULL,
                    progress TEXT NOT NULL DEFAULT '{}', error TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS drafts (
                    job_id TEXT NOT NULL REFERENCES jobs(id), revision INTEGER NOT NULL,
                    data TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(job_id, revision));
                CREATE TABLE IF NOT EXISTS artifacts (
                    job_id TEXT NOT NULL REFERENCES jobs(id), path TEXT NOT NULL,
                    kind TEXT NOT NULL, metadata TEXT NOT NULL,
                    PRIMARY KEY(job_id,path));
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path / "workspace.sqlite3", timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def add_source(self, path: Path) -> dict:
        from .sources import MAX_SOURCE_BYTES, chunks, extract_source

        path = Path(path)
        try:
            with path.open("rb") as incoming:
                data = incoming.read(MAX_SOURCE_BYTES + 1)
        except OSError as error:
            raise ValueError(f"Cannot read source file {path.name}: {error.strerror}") from error
        if len(data) > MAX_SOURCE_BYTES:
            raise ValueError(f"Source exceeds the {MAX_SOURCE_BYTES}-byte size limit")
        digest = hashlib.sha256(data).hexdigest()
        with self.connect() as db:
            found = db.execute("SELECT * FROM sources WHERE hash=?", (digest,)).fetchone()
            if found:
                return dict(found)
        source_id = digest[:20]
        relative = Path("originals") / (digest + path.suffix.lower())
        original = self.path / relative
        original.parent.mkdir(exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            dir=original.parent, prefix=".import-", suffix=path.suffix.lower()
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            # Parse the exact bytes hashed above. The caller's path may change
            # during import, but the stored original and extracted text cannot diverge.
            units = chunks(extract_source(Path(temporary)))
            if not original.exists():
                os.replace(temporary, original)
        finally:
            Path(temporary).unlink(missing_ok=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            found = db.execute("SELECT * FROM sources WHERE hash=?", (digest,)).fetchone()
            if found:
                return dict(found)
            db.execute(
                "INSERT INTO sources VALUES (?,?,?,?,?)",
                (source_id, path.name, digest, str(relative), time.time()),
            )
            for index, unit in enumerate(units):
                db.execute(
                    "INSERT INTO units VALUES (?,?,?,?,?)",
                    (
                        f"{source_id}:{index + 1}",
                        source_id,
                        unit["locator"],
                        unit["text"],
                        unit["status"],
                    ),
                )
        return next(s for s in self.sources() if s["id"] == source_id)

    def sources(self) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM sources ORDER BY created,id")]

    def units(self, source_ids: list[str] | None = None) -> list[dict]:
        with self.connect() as db:
            if source_ids is None:
                rows = db.execute("SELECT * FROM units ORDER BY source_id,rowid")
            elif not source_ids:
                return []
            else:
                marks = ",".join("?" for _ in source_ids)
                rows = db.execute(
                    f"SELECT * FROM units WHERE source_id IN ({marks}) ORDER BY source_id,rowid",
                    source_ids,
                )
            return [dict(r) for r in rows]

    def submit(self, kind: str, params: dict, request_key: str | None = None) -> dict:
        now = time.time()
        key = request_key or uuid.uuid4().hex
        encoded = json.dumps(params, ensure_ascii=False, sort_keys=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM jobs WHERE request_key=?", (key,)).fetchone()
            if previous:
                if previous["kind"] != kind or previous["params"] != encoded:
                    raise ValueError("Request key already belongs to a different operation")
                return self._job(previous)
            job_id = uuid.uuid4().hex[:16]
            db.execute(
                "INSERT INTO jobs(id,kind,params,request_key,status,created,updated) "
                "VALUES(?,?,?,?,?,?,?)",
                (job_id, kind, encoded, key, "queued", now, now),
            )
        return self.job(job_id)

    @staticmethod
    def _job(row) -> dict:
        result = dict(row)
        result["params"] = json.loads(result["params"])
        result["progress"] = json.loads(result["progress"])
        return result

    def jobs(self) -> list[dict]:
        with self.connect() as db:
            return [self._job(r) for r in db.execute("SELECT * FROM jobs ORDER BY created DESC")]

    def job(self, job_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise ValueError(f"Unknown job: {job_id}")
            return self._job(row)

    def claim(self) -> dict | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created LIMIT 1")
            row = row.fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE jobs SET status='running',updated=? WHERE id=?", (time.time(), row["id"])
            )
        return self.job(row["id"])

    def update_job(self, job_id: str, *, status=None, progress=None, error=None):
        with self.connect() as db:
            if status is not None:
                db.execute(
                    "UPDATE jobs SET status=CASE WHEN ?='succeeded' AND cancel_requested=1 "
                    "THEN 'cancelled' ELSE ? END,error=?,updated=? WHERE id=?",
                    (status, status, error, time.time(), job_id),
                )
            if progress is not None:
                db.execute(
                    "UPDATE jobs SET progress=?,updated=? WHERE id=?",
                    (json.dumps(progress, ensure_ascii=False), time.time(), job_id),
                )

    def cancel(self, job_id: str) -> dict:
        self.job(job_id)
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET cancel_requested=1, status=CASE WHEN status='queued' "
                "THEN 'cancelled' ELSE status END,updated=? WHERE id=?",
                (time.time(), job_id),
            )
        return self.job(job_id)

    def resume(self, job_id: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row[0] not in ("failed", "cancelled", "interrupted"):
                raise ValueError("Only failed, cancelled or interrupted jobs can be resumed")
            db.execute(
                "UPDATE jobs SET status='queued',cancel_requested=0,error=NULL,updated=? "
                "WHERE id=?",
                (time.time(), job_id),
            )
        return self.job(job_id)

    def recover(self):
        # Must be called only by the process holding the workspace OS lock.
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET status='interrupted',updated=? WHERE status='running'",
                (time.time(),),
            )

    def save_draft(self, job_id: str, data: dict, expected_revision: int = 0) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute(
                "SELECT COALESCE(MAX(revision),0) FROM drafts WHERE job_id=?", (job_id,)
            ).fetchone()[0]
            if version != expected_revision:
                raise ValueError("Draft changed. Reload it before saving your edits.")
            db.execute(
                "INSERT INTO drafts VALUES (?,?,?,?)",
                (job_id, version + 1, json.dumps(data, ensure_ascii=False), time.time()),
            )
        return self.draft(job_id, version + 1)

    def draft(self, job_id: str, revision: int | None = None) -> dict | None:
        with self.connect() as db:
            if revision is None:
                row = db.execute(
                    "SELECT * FROM drafts WHERE job_id=? ORDER BY revision DESC LIMIT 1", (job_id,)
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT * FROM drafts WHERE job_id=? AND revision=?", (job_id, revision)
                ).fetchone()
        return None if row is None else {**dict(row), "data": json.loads(row["data"])}

    def add_artifact(self, job_id: str, path: Path, kind: str, metadata: dict):
        relative = path.resolve().relative_to(self.path)
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?)",
                (job_id, str(relative), kind, json.dumps(metadata, ensure_ascii=False)),
            )

    def artifacts(self, job_id: str) -> list[dict]:
        with self.connect() as db:
            return [
                {**dict(r), "metadata": json.loads(r["metadata"])}
                for r in db.execute("SELECT * FROM artifacts WHERE job_id=?", (job_id,))
            ]
