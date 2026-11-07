"""Shared labels for saved job kinds and states."""

from brofessor.contracts.jobs import JobKind, JobStatus, TaskStatus

JOB_LABELS = {
    JobKind.TRANSLATE_EPUB: "Book translation",
    JobKind.TRANSLATE_PDF: "PDF translation",
    JobKind.RENDER_EPUB: "EPUB",
    JobKind.RENDER_PDF: "PDF",
    JobKind.CHECK_PODCAST: "Script check",
    JobKind.PODCAST: "Podcast script",
    JobKind.SLIDES: "Slide outline",
    JobKind.PODCAST_SERIES: "Podcast series",
    JobKind.ASK: "Answer",
    JobKind.REPORT: "Written report",
    JobKind.STUDY: "Practice questions",
    JobKind.AUDIOBOOK: "Audiobook text",
    JobKind.RENDER_AUDIOBOOK: "Audiobook",
    JobKind.REVIEW_STUDY: "Answer feedback",
    JobKind.PREVIEW_TURN: "Turn preview",
    JobKind.RENDER_PODCAST: "Audio",
    JobKind.RENDER_SLIDES: "Presentation",
    JobKind.DOWNLOAD_MODEL: "TTS model download",
}


STATUS_LABELS = {
    JobStatus.SUCCEEDED: "Ready",
    JobStatus.FAILED: "Failed",
    JobStatus.QUEUED: "Queued",
    JobStatus.RUNNING: "Running",
    JobStatus.CANCELLED: "Cancelled",
    JobStatus.INTERRUPTED: "Interrupted",
    TaskStatus.BLOCKED: "Needs attention",
}
