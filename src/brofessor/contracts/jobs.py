"""Durable job values. Serialized records retain their historical string fields."""

from enum import StrEnum
from typing import Final, NotRequired, TypedDict


class JobKind(StrEnum):
    ASK = "ask"
    REPORT = "report"
    STUDY = "study"
    REVIEW_STUDY = "review_study"
    AUDIOBOOK = "audiobook"
    RENDER_AUDIOBOOK = "render_audiobook"
    SLIDES = "slides"
    PODCAST = "podcast"
    PODCAST_SERIES = "podcast_series"
    RENDER_SLIDES = "render_slides"
    RENDER_PODCAST = "render_podcast"
    PREVIEW_TURN = "preview_turn"
    DOWNLOAD_MODEL = "download_model"
    DOWNLOAD_OLLAMA_MODEL = "download_ollama_model"
    CHECK_PODCAST = "check_podcast"
    TRANSLATE_EPUB = "translate_epub"
    RENDER_EPUB = "render_epub"
    TRANSLATE_PDF = "translate_pdf"
    RENDER_PDF = "render_pdf"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


SUPPORTED_JOB_KINDS: Final = frozenset(JobKind)
ALL_TASK_KINDS_FILTER: Final = "all"
ACTIVE_JOB_STATUSES: Final = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})
TERMINAL_JOB_STATUSES: Final = frozenset(
    {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.INTERRUPTED}
)
RESUMABLE_JOB_STATUSES: Final = frozenset(
    {JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.INTERRUPTED}
)
PRIMARY_JOB_KINDS: Final = frozenset(
    {
        JobKind.ASK,
        JobKind.REPORT,
        JobKind.STUDY,
        JobKind.AUDIOBOOK,
        JobKind.PODCAST,
        JobKind.PODCAST_SERIES,
        JobKind.SLIDES,
        JobKind.TRANSLATE_EPUB,
        JobKind.TRANSLATE_PDF,
    }
)
TEXT_JOB_KINDS: Final = frozenset(
    {
        JobKind.ASK,
        JobKind.REPORT,
        JobKind.STUDY,
        JobKind.REVIEW_STUDY,
        JobKind.SLIDES,
        JobKind.PODCAST,
        JobKind.PODCAST_SERIES,
        JobKind.CHECK_PODCAST,
        JobKind.TRANSLATE_EPUB,
        JobKind.TRANSLATE_PDF,
    }
)
TRANSLATION_JOB_KINDS: Final = frozenset({JobKind.TRANSLATE_EPUB, JobKind.TRANSLATE_PDF})
PODCAST_JOB_KINDS: Final = frozenset({JobKind.PODCAST, JobKind.PODCAST_SERIES})
AUDIO_RENDER_JOB_KINDS: Final = frozenset(
    {JobKind.RENDER_PODCAST, JobKind.PREVIEW_TURN, JobKind.RENDER_AUDIOBOOK}
)
DOWNLOAD_JOB_KINDS: Final = frozenset({JobKind.DOWNLOAD_MODEL, JobKind.DOWNLOAD_OLLAMA_MODEL})
RETRIEVAL_JOB_KINDS: Final = frozenset({JobKind.ASK, JobKind.REPORT, JobKind.STUDY})
CONSOLIDATION_JOB_KINDS: Final = frozenset(
    {JobKind.SLIDES, JobKind.PODCAST, JobKind.PODCAST_SERIES}
)
READING_WORKFLOW_JOB_KINDS: Final = RETRIEVAL_JOB_KINDS | CONSOLIDATION_JOB_KINDS


class StageId(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    READING = "reading"
    SEARCHING = "searching"
    SOURCE_NAVIGATION = "source_navigation"
    CONSOLIDATING = "consolidating"
    OUTLINE = "outline"
    SERIES_PLAN = "series_plan"
    SCRIPT = "script"
    WRITING = "writing"
    VALIDATING = "validating"
    SAVING = "saving"
    SPEECH = "speech"
    AUDIO_PREPARING = "audio_preparing"
    AUDIO_PACKAGING = "audio_packaging"
    WAITING_FOR_SPEECH = "waiting_for_speech"
    GLOSSARY = "glossary"
    GLOSSARY_REVIEW = "glossary_review"
    TRANSLATION = "translation"
    TERMINOLOGY_UPDATE = "terminology_update"
    CHECKING_SCRIPT = "checking_script"
    STUDY_REVIEW = "study_review"
    DOWNLOADING_MODEL = "downloading_model"
    RENDERING = "rendering"
    DRAFT_READY = "draft_ready"
    TRANSLATED_BOOK = "translated_book"
    CHECKED_SCRIPT = "checked_script"


class StageState(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    SKIPPED = "skipped"
    PENDING = "pending"
    BLOCKED = "blocked"
    UNMEASURED = "unmeasured"


class InitialAudioState(StrEnum):
    PENDING = "pending"
    BLOCKED = "blocked"
    QUEUED = "queued"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    """Additional presentation states; never written to jobs.status."""

    BLOCKED = "blocked"
    PENDING = "pending"


class JobProgress(TypedDict, total=False):
    # Stage-specific measurements remain extensible JSON, including older stages.
    stage: str
    completed: int | float
    total: int | float
    reused_checkpoints: int
    waiting_for_model: bool


class JobRecord(TypedDict):
    id: str
    kind: str
    params: dict
    request_key: str
    status: str
    progress: JobProgress
    error: str | None
    cancel_requested: int
    created: float
    updated: float
    notice: NotRequired[str]


class DraftRecord(TypedDict):
    job_id: str
    revision: int
    data: dict
    created: float


class InitialAudioRecord(TypedDict):
    job_id: str
    revision: int | None
    state: str
    render_id: str | None
    error: str | None
    render: NotRequired[JobRecord]


class ModelChoicesRecord(TypedDict):
    task_id: str
    revision: int
    data: dict


class TaskSummary(TypedDict):
    root_id: str
    child_id: str
    match_id: str
    match_title: str
    title: str
    kind: str
    status: str
    workspace_path: str
    created: float
