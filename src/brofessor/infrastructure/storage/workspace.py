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
from typing import Final, cast

from brofessor.contracts.content import ArtifactRecord, SourceRecord, SourceUnit
from brofessor.contracts.jobs import (
    RESUMABLE_JOB_STATUSES,
    DraftRecord,
    InitialAudioState,
    JobKind,
    JobRecord,
    JobStatus,
    ModelChoicesRecord,
    StageId,
)

DATABASE_FILENAME: Final = "workspace.sqlite3"
ORIGINALS_DIRECTORY: Final = "originals"
JOBS_DIRECTORY: Final = "jobs"
AUDIO_SEGMENTS_DIRECTORY: Final = "audio-segments"
WORKSPACE_SCHEMA_VERSION: Final = 6


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
            if version == WORKSPACE_SCHEMA_VERSION:
                return
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == WORKSPACE_SCHEMA_VERSION:
                return
            existing = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1"
            ).fetchone()
            if version != 0 or existing:
                raise ValueError(f"Unsupported workspace schema {version}; create a new project")
            schema = """
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, hash TEXT UNIQUE NOT NULL,
                    original TEXT NOT NULL, created REAL NOT NULL, hidden INTEGER NOT NULL DEFAULT 0);
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
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL,
                    origin TEXT, created REAL NOT NULL, PRIMARY KEY(id,revision));
                CREATE TABLE IF NOT EXISTS task_models (
                    task_id TEXT PRIMARY KEY REFERENCES jobs(id),
                    revision INTEGER NOT NULL, data TEXT NOT NULL);
            """
            for statement in schema.split(";"):
                if statement.strip():
                    db.execute(statement)
            db.execute(
                "CREATE TABLE IF NOT EXISTS collections (id TEXT PRIMARY KEY, root TEXT UNIQUE NOT NULL, created REAL NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS deleted_tasks (root_id TEXT PRIMARY KEY REFERENCES jobs(id), deleted REAL NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS task_names (task_id TEXT PRIMARY KEY REFERENCES jobs(id), title TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS initial_audio (job_id TEXT PRIMARY KEY REFERENCES jobs(id), revision INTEGER, state TEXT NOT NULL, render_id TEXT, error TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS job_stages (id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), stage TEXT NOT NULL, state TEXT NOT NULL, started REAL NOT NULL, ended REAL, elapsed REAL NOT NULL DEFAULT 0, touched REAL NOT NULL, data TEXT NOT NULL DEFAULT '{}')"
            )
            db.execute("CREATE INDEX IF NOT EXISTS job_stages_job ON job_stages(job_id,id)")
            db.execute(f"PRAGMA user_version={WORKSPACE_SCHEMA_VERSION}")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path / DATABASE_FILENAME, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def add_source(self, path: Path, *, name=None, hidden=False) -> SourceRecord:
        from brofessor.infrastructure.formats.ingestion import (
            MAX_SOURCE_BYTES,
            chunks,
            extract_source,
        )

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
                if not hidden and found["hidden"]:
                    db.execute("UPDATE sources SET hidden=0 WHERE id=?", (found["id"],))
                    return cast(SourceRecord, {**dict(found), "hidden": 0})
                return cast(SourceRecord, dict(found))
        source_id = digest[:20]
        relative = Path(ORIGINALS_DIRECTORY) / (digest + path.suffix.lower())
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
                if not hidden and found["hidden"]:
                    db.execute("UPDATE sources SET hidden=0 WHERE id=?", (found["id"],))
                    return cast(SourceRecord, {**dict(found), "hidden": 0})
                return cast(SourceRecord, dict(found))
            db.execute(
                "INSERT INTO sources(id,name,hash,original,created,hidden) VALUES (?,?,?,?,?,?)",
                (source_id, name or path.name, digest, str(relative), time.time(), int(hidden)),
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

    def sources(self) -> list[SourceRecord]:
        with self.connect() as db:
            return [
                cast(SourceRecord, dict(r))
                for r in db.execute("SELECT * FROM sources ORDER BY created,id")
            ]

    def units(self, source_ids: list[str] | None = None) -> list[SourceUnit]:
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
            return [cast(SourceUnit, dict(r)) for r in rows]

    def submit(
        self,
        kind: str,
        params: dict,
        request_key: str | None = None,
        *,
        reuse_active=False,
        task_models: dict | None = None,
    ) -> JobRecord:
        now = time.time()
        key = request_key or uuid.uuid4().hex
        encoded = json.dumps(params, ensure_ascii=False, sort_keys=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_visible_task(db, {"id": "", "params": params})
            if reuse_active:
                active = db.execute(
                    "SELECT * FROM jobs WHERE kind=? AND params=? AND status IN (?,?)",
                    (kind, encoded, JobStatus.QUEUED, JobStatus.RUNNING),
                ).fetchone()
                if active:
                    return self._job(active)
            previous = db.execute("SELECT * FROM jobs WHERE request_key=?", (key,)).fetchone()
            if previous:
                if previous["kind"] != kind or previous["params"] != encoded:
                    raise ValueError("Request key already belongs to a different operation")
                return self._job(previous)
            job_id = uuid.uuid4().hex[:16]
            db.execute(
                "INSERT INTO jobs(id,kind,params,request_key,status,created,updated) "
                "VALUES(?,?,?,?,?,?,?)",
                (job_id, kind, encoded, key, JobStatus.QUEUED, now, now),
            )
            from brofessor.application.progress import record

            record(db, job_id, stage=StageId.QUEUED, now=now)
            if kind == JobKind.PODCAST and params.get("auto_audio"):
                db.execute(
                    "INSERT INTO initial_audio(job_id,state) VALUES (?, ?)",
                    (job_id, InitialAudioState.PENDING),
                )
            if task_models is not None:
                db.execute(
                    "INSERT INTO task_models VALUES (?,1,?)",
                    (job_id, json.dumps(task_models, ensure_ascii=False)),
                )
        return self.job(job_id)

    def task_models(self, task_id: str) -> ModelChoicesRecord | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM task_models WHERE task_id=?", (task_id,)).fetchone()
            return (
                {"task_id": task_id, "revision": row["revision"], "data": json.loads(row["data"])}
                if row
                else None
            )

    def save_task_models(
        self, task_id: str, data: dict, expected_revision: int
    ) -> ModelChoicesRecord:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT id FROM jobs WHERE id=?", (task_id,)).fetchone() is None:
                raise ValueError("Unknown task")
            row = db.execute(
                "SELECT revision FROM task_models WHERE task_id=?", (task_id,)
            ).fetchone()
            version = row[0] if row else 0
            if expected_revision != version:
                raise ValueError("Task models changed. Reload before saving.")
            db.execute(
                "INSERT INTO task_models VALUES (?,?,?) ON CONFLICT(task_id) DO UPDATE SET revision=excluded.revision,data=excluded.data",
                (task_id, version + 1, json.dumps(data, ensure_ascii=False)),
            )
        saved = self.task_models(task_id)
        assert saved is not None  # The committed row exists even if another writer updates it.
        return saved

    @staticmethod
    def _job(row: sqlite3.Row) -> JobRecord:
        result = dict(row)
        result["params"] = json.loads(result["params"])
        result["progress"] = json.loads(result["progress"])
        return cast(JobRecord, result)

    def _require_visible_task(self, db, job):
        from brofessor.application.tasks import root_job

        deleted = {r[0] for r in db.execute("SELECT root_id FROM deleted_tasks")}
        if not deleted:
            return
        by_id = {r["id"]: self._job(r) for r in db.execute("SELECT * FROM jobs")}
        if root_job(job, by_id) in deleted:
            raise ValueError("Restore this task before starting more work")

    def jobs(self) -> list[JobRecord]:
        with self.connect() as db:
            return [self._job(r) for r in db.execute("SELECT * FROM jobs ORDER BY created DESC")]

    def job_by_request_key(self, key: str) -> JobRecord | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE request_key=?", (key,)).fetchone()
            return self._job(row) if row is not None else None

    def job(self, job_id: str) -> JobRecord:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise ValueError(f"Unknown job: {job_id}")
            return self._job(row)

    def claim(self) -> JobRecord | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id FROM jobs WHERE status=? ORDER BY created LIMIT 1", (JobStatus.QUEUED,)
            )
            row = row.fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE jobs SET status=?,updated=? WHERE id=?",
                (JobStatus.RUNNING, time.time(), row["id"]),
            )
            from brofessor.application.progress import record

            record(db, row["id"], stage=StageId.PREPARING)
        return self.job(row["id"])

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: dict | None = None,
        error: str | None = None,
    ) -> None:
        with self.connect() as db:
            if status is not None:
                db.execute(
                    "UPDATE jobs SET status=CASE WHEN ?=? AND cancel_requested=1 "
                    "THEN ? ELSE ? END,error=?,updated=? WHERE id=?",
                    (
                        status,
                        JobStatus.SUCCEEDED,
                        JobStatus.CANCELLED,
                        status,
                        error,
                        time.time(),
                        job_id,
                    ),
                )
            if progress is not None:
                db.execute(
                    "UPDATE jobs SET progress=?,updated=? WHERE id=?",
                    (json.dumps(progress, ensure_ascii=False), time.time(), job_id),
                )
            from brofessor.application.progress import record

            record(
                db,
                job_id,
                stage=progress.get("stage") if progress else None,
                data=progress,
                status=self._job(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())[
                    "status"
                ]
                if status
                else None,
            )

    def cancel(self, job_id: str) -> JobRecord:
        self.job(job_id)
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET cancel_requested=1, status=CASE WHEN status=? "
                "THEN ? ELSE status END,updated=? WHERE id=?",
                (JobStatus.QUEUED, JobStatus.CANCELLED, time.time(), job_id),
            )
        if self.job(job_id)["status"] == JobStatus.CANCELLED:
            with self.connect() as db:
                from brofessor.application.progress import record

                record(db, job_id, status=JobStatus.CANCELLED)
        from brofessor.application.initial_audio import cancel

        cancel(self, job_id)
        return self.job(job_id)

    def resume(self, job_id: str) -> JobRecord:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row[0] not in RESUMABLE_JOB_STATUSES:
                raise ValueError("Only failed, cancelled or interrupted jobs can be resumed")
            job = self._job(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            self._require_visible_task(db, job)
            db.execute(
                "UPDATE jobs SET status=?,cancel_requested=0,error=NULL,updated=? WHERE id=?",
                (JobStatus.QUEUED, time.time(), job_id),
            )
            db.execute(
                "UPDATE initial_audio SET state=?,error=NULL WHERE render_id=?",
                (InitialAudioState.QUEUED, job_id),
            )
            from brofessor.application.progress import record

            record(db, job_id, stage=StageId.QUEUED)
        return self.job(job_id)

    def recover(self):
        # Must be called only by the process holding the workspace OS lock.
        with self.connect() as db:
            from brofessor.application.progress import record

            for row in db.execute(
                "SELECT id FROM jobs WHERE status=?", (JobStatus.RUNNING,)
            ).fetchall():
                record(db, row[0], status=JobStatus.INTERRUPTED, recovered=True)
            db.execute(
                "UPDATE jobs SET status=?,updated=? WHERE status=?",
                (JobStatus.INTERRUPTED, time.time(), JobStatus.RUNNING),
            )

    def save_draft(self, job_id: str, data: dict, expected_revision: int = 0) -> DraftRecord:
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
        saved = self.draft(job_id, version + 1)
        assert saved is not None  # Draft revisions are append-only.
        return saved

    def draft(self, job_id: str, revision: int | None = None) -> DraftRecord | None:
        with self.connect() as db:
            if revision is None:
                row = db.execute(
                    "SELECT * FROM drafts WHERE job_id=? ORDER BY revision DESC LIMIT 1", (job_id,)
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT * FROM drafts WHERE job_id=? AND revision=?", (job_id, revision)
                ).fetchone()
        return (
            None
            if row is None
            else cast(DraftRecord, {**dict(row), "data": json.loads(row["data"])})
        )

    def add_artifact(self, job_id: str, path: Path, kind: str, metadata: dict):
        relative = path.resolve().relative_to(self.path)
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?)",
                (job_id, str(relative), kind, json.dumps(metadata, ensure_ascii=False)),
            )

    @staticmethod
    def _note(row):
        return (
            None
            if row is None
            else {
                **dict(row),
                "data": json.loads(row["data"]),
                "origin": json.loads(row["origin"]) if row["origin"] else None,
            }
        )

    def note(self, note_id: str, revision: int | None = None):
        with self.connect() as db:
            if revision is None:
                row = db.execute(
                    "SELECT * FROM notes WHERE id=? ORDER BY revision DESC LIMIT 1", (note_id,)
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT * FROM notes WHERE id=? AND revision=?", (note_id, revision)
                ).fetchone()
        return self._note(row)

    def notes(self):
        with self.connect() as db:
            return [
                self._note(row)
                for row in db.execute(
                    "SELECT * FROM notes WHERE (id,revision) IN (SELECT id,MAX(revision) FROM notes GROUP BY id) ORDER BY created DESC,id"
                )
            ]

    def create_note(self, data, *, note_id=None, origin=None):
        """A supplied ID creates once; retries return the latest saved revision."""
        note_id = note_id or uuid.uuid4().hex[:16]
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO notes VALUES (?,1,?,?,?)",
                (
                    note_id,
                    json.dumps(data, ensure_ascii=False),
                    json.dumps(origin) if origin else None,
                    time.time(),
                ),
            )
        return self.note(note_id)

    def save_note(self, note_id, data, expected_revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT * FROM notes WHERE id=? ORDER BY revision DESC LIMIT 1", (note_id,)
            ).fetchone()
            if previous is None:
                raise ValueError("Note does not exist")
            if previous["revision"] != expected_revision:
                raise ValueError("Note changed. Reload it before saving your edits.")
            db.execute(
                "INSERT INTO notes VALUES (?,?,?,?,?)",
                (
                    note_id,
                    expected_revision + 1,
                    json.dumps(data, ensure_ascii=False),
                    previous["origin"],
                    time.time(),
                ),
            )
        return self.note(note_id, expected_revision + 1)

    def artifacts(self, job_id: str) -> list[ArtifactRecord]:
        with self.connect() as db:
            return [
                cast(ArtifactRecord, {**dict(r), "metadata": json.loads(r["metadata"])})
                for r in db.execute("SELECT * FROM artifacts WHERE job_id=?", (job_id,))
            ]
