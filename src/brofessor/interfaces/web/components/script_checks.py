"""Present an optional, revision-specific source review without editing the script."""

import json

import streamlit as st

from brofessor.application import service
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.features.podcasts import checks as script_checks
from brofessor.features.podcasts.checks import CheckStatus
from brofessor.interfaces.web.components import layout as ui_layout


def show(workspace, job, revision, saved, t, status_view, *, status_area):
    with ui_layout.section(t("Check script against sources"), job["id"] + ":script-check"):
        st.caption(
            t(
                "Review saved wording against cited originals. Findings need editorial review and do not change the script."
            )
        )
        if st.button(t("Check script"), key=f"script-check-start:{job['id']}", disabled=not saved):
            try:
                result = service.check_script(workspace, job["id"], revision=revision)
                st.session_state[f"script-check-selected:{workspace.path}:{job['id']}"] = result[
                    "id"
                ]
                st.rerun()
            except (OSError, ValueError, RuntimeError) as error:
                st.error(t("Could not submit the job: {error}", error=error))
        if not saved:
            st.caption(t("Save or load a saved revision before checking the script."))
        history = [
            item
            for item in workspace.jobs()
            if item["kind"] == JobKind.CHECK_PODCAST and item["params"]["draft_job_id"] == job["id"]
        ]
        if not history:
            return
        by_id = {item["id"]: item for item in history}
        labels = {
            JobStatus.QUEUED: "Queued",
            JobStatus.RUNNING: "Running",
            JobStatus.FAILED: "Failed",
            JobStatus.INTERRUPTED: "Interrupted",
            JobStatus.CANCELLED: "Cancelled",
            JobStatus.SUCCEEDED: "Check completed",
        }
        selected = st.selectbox(
            t("Script checks"),
            list(by_id),
            format_func=lambda key: t(
                "Revision {revision} · {status}",
                revision=by_id[key]["params"]["revision"],
                status=t(labels[by_id[key]["status"]]),
            ),
            key=f"script-check-selected:{workspace.path}:{job['id']}",
        )
        if by_id[selected]["status"] == JobStatus.SUCCEEDED:
            status_view(selected, scope="script-check:")
        else:
            with status_area:
                ui_layout.heading(t("Script check"), level=4)
                status_view(selected, scope="script-check:")
        report = script_checks.report(workspace, selected)
        if report is None:
            return
        st.caption(t("Report for saved revision {revision}", revision=report["revision"]))
        assessments = report["assessments"]
        needs = sum(item["status"] == CheckStatus.NEEDS_CONTEXT for item in assessments)
        st.caption(
            t(
                "Reviewed {count} of {total} turns · Need context {needs} · Unchecked {unchecked}",
                count=len(assessments),
                total=report["total_turns"],
                needs=needs,
                unchecked=len(report["unchecked"]) + len(report["pending_turns"]),
            )
        )
        st.caption(
            t(
                "Scope: cited originals and nearby fragments. This report does not establish that the whole source supports every claim."
            )
        )
        origins = {item["id"]: item for packet in report["packets"] for item in packet["originals"]}
        for row in assessments:
            if row["status"] == CheckStatus.SUPPORTED:
                continue
            ui_layout.heading(
                t("Turn {number}", number=row["turn"])
                + " · "
                + t(
                    "Needs more context"
                    if row["status"] == CheckStatus.NEEDS_CONTEXT
                    else "Review finding"
                ),
                level=4,
            )
            st.text(row["explanation"])
            for finding in row["findings"]:
                st.text(finding["claim"])
                st.text(finding["explanation"])
            quotes = [
                *row["quotes"],
                *(quote for finding in row["findings"] for quote in finding["quotes"]),
            ]
            seen = set()
            for quote in quotes:
                identity = (quote["citation"], quote["text"])
                if identity in seen:
                    continue
                seen.add(identity)
                origin = origins[quote["citation"]]
                st.caption(origin["source"] + " · " + origin["locator"])
                st.text(quote["text"])
        if report["unchecked"]:
            st.caption(
                t(
                    "Some turns could not fit a bounded original context. They have no model verdict."
                )
            )
        if not any(item["status"] != CheckStatus.SUPPORTED for item in assessments):
            st.caption(
                t("No findings in the reviewed turns. This is a model assessment, not an approval.")
            )
        st.download_button(
            t("Download check report"),
            json.dumps(report, ensure_ascii=False, indent=2),
            file_name=f"script-check-r{report['revision']}.json",
            mime="application/json",
            key="script-check-download:" + selected,
        )
