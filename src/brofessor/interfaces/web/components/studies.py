"""Present revision-specific learner feedback using the ordinary task controls."""

import streamlit as st

from brofessor.application import service
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.features import studies
from brofessor.features.studies import FeedbackAssessment
from brofessor.interfaces.web.components import layout as ui_layout
from brofessor.interfaces.web.state_keys import widget_options


def show(workspace, job, draft, saved, t, status_view, *, status_area):
    if st.button(
        t("Check answers"),
        key=f"study-review:{job['id']}",
        disabled=not saved or not any(v.strip() for v in draft["data"]["answers"].values()),
    ):
        try:
            result = studies.submit_review(workspace, job["id"], revision=draft["revision"])
            st.session_state[f"study-feedback:{workspace.path}:{job['id']}"] = result["id"]
            st.rerun()
        except (ValueError, OSError, RuntimeError) as error:
            st.error(t("Could not submit the job: {error}", error=error))
    if not saved:
        st.caption(t("Save your answers before checking them."))
    reviews = {
        j["id"]: j
        for j in workspace.jobs()
        if j["kind"] == JobKind.REVIEW_STUDY and j["params"]["draft_job_id"] == job["id"]
    }
    if not reviews:
        return
    with ui_layout.section(t("Answer feedback"), job["id"] + ":feedback", expanded=True):
        show_feedback(workspace, job, reviews, t, status_view, status_area)


def show_feedback(workspace, job, reviews, t, status_view, status_area):
    labels = {
        JobStatus.QUEUED: "Queued",
        JobStatus.RUNNING: "Running",
        JobStatus.FAILED: "Failed",
        JobStatus.INTERRUPTED: "Interrupted",
        JobStatus.CANCELLED: "Cancelled",
        JobStatus.SUCCEEDED: "Check completed",
    }
    selected = st.selectbox(
        t("Answer reviews"),
        widget_options(list(reviews)),
        format_func=lambda key: (
            f"r{reviews[key]['params']['revision']} · {t(labels[reviews[key]['status']])}"
        ),
        key=f"study-feedback:{workspace.path}:{job['id']}",
    )
    if reviews[selected]["status"] == JobStatus.SUCCEEDED:
        status_view(selected, scope="study-review:")
    else:
        with status_area:
            ui_layout.heading(t("Answer feedback"), level=4)
            status_view(selected, scope="study-review:")
    feedback = workspace.draft(selected)
    if feedback is None:
        return
    revision = reviews[selected]["params"]["revision"]
    source = workspace.draft(job["id"], revision)["data"]
    by_id = {q["id"]: q for q in source["questions"]}
    evidence = {e["citation"]: e for e in service.answer_evidence(workspace, selected)}
    st.caption(t("Feedback for saved answers revision {revision}", revision=revision))
    for finding in feedback["data"]["findings"]:
        ui_layout.heading(by_id[finding["question_id"]]["prompt"], level=4)
        st.caption(
            t(
                {
                    FeedbackAssessment.SUPPORTED: "Answer supported",
                    FeedbackAssessment.PARTIAL: "Partly supported",
                    FeedbackAssessment.NEEDS_WORK: "Needs revision",
                    FeedbackAssessment.INSUFFICIENT_CONTEXT: "Needs more context",
                }[finding["assessment"]]
            )
        )
        st.text(finding["feedback"])
        with st.expander(t("Saved learner answer")):
            st.text(source["answers"][finding["question_id"]])
        for quote in finding["quotes"]:
            item = evidence[quote["citation"]]
            st.caption(item["source"] + " · " + item["locator"])
            st.text(quote["text"])
    if feedback["data"]["unanswered"]:
        st.caption(
            t(
                "Unanswered questions: {questions}",
                questions=", ".join(feedback["data"]["unanswered"]),
            )
        )
