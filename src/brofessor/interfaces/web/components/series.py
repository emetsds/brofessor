"""Web components: series."""

import streamlit as st

from brofessor.application import service
from brofessor.contracts.jobs import JobStatus
from brofessor.interfaces.web.state_keys import widget_options


def series_actions(context, job, plan, saved, group):
    workspace = context.workspace
    t = context.t
    revision = plan["revision"]
    episodes = plan["data"]["episodes"]
    number = st.selectbox(
        t("Episode from saved plan · revision {revision}", revision=revision),
        widget_options(range(1, len(episodes) + 1)),
        format_func=lambda n: f"{n}. {episodes[n - 1]['title']}",
        key=f"series-episode-{job['id']}",
    )
    origin = {"job_id": job["id"], "revision": revision, "episode": number}
    existing = next((child for child in group if child["params"].get("series") == origin), None)
    if existing:
        st.button(
            t("Open episode"),
            key=f"open-episode-{job['id']}",
            on_click=context.open_result,
            args=(existing["id"],),
        )
        return
    if not saved:
        st.caption(t("Save or load the latest plan before preparing an episode."))
    if st.button(
        t("Prepare episode"),
        key=f"prepare-episode-{job['id']}",
        disabled=not saved or job["status"] != JobStatus.SUCCEEDED,
    ):
        try:
            child = service.series_episode(workspace, job["id"], number, revision=revision)
            context.open_result(child["id"])
            st.rerun()
        except (OSError, ValueError) as error:
            st.error(t("Could not submit the job: {error}", error=error))
