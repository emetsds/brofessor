"""Shared presentation roles for the Streamlit client; no application state."""

import html
from contextlib import contextmanager
from importlib.resources import files

import streamlit as st

from brofessor.interfaces.web.state_keys import SECTION_DEFAULT_PREFIX

STYLES = """<style>
[data-testid="stMainBlockContainer"] {padding-top:3.5rem}
.brofessor-prose {font-family:inherit;font-size:1rem;line-height:1.75;max-width:70ch;white-space:normal;overflow-wrap:anywhere;margin-bottom:.75rem}
.brofessor-table {overflow-x:auto;margin:1rem 0}.brofessor-table table {border-collapse:collapse;width:100%}.brofessor-table th,.brofessor-table td {padding:.5rem .75rem;border-bottom:1px solid #8884;text-align:left;overflow-wrap:anywhere}
.st-key-app-brand h3 {font-size:1.15rem;letter-spacing:-.03em}
.st-key-task-catalogue {gap:.5rem}
.st-key-task-catalogue [class*="st-key-task-row-"] {gap:0;padding:.35rem 0;border-bottom:1px solid #8882}
.st-key-task-catalogue button[kind="tertiary"] {width:100%;min-height:2.25rem;text-align:left;justify-content:flex-start;border:0;background:transparent;padding:.2rem 0;color:inherit}
.st-key-task-catalogue button[kind="tertiary"] > div {width:100%;justify-content:flex-start}
.st-key-task-catalogue button[kind="tertiary"] p {text-align:left;white-space:normal;font-weight:500}
.st-key-task-catalogue [class*="st-key-task-row-"] > [data-testid="stElementContainer"] [data-testid="stCaptionContainer"] {padding-left:1.8rem}
.st-key-task-catalogue button[kind="tertiary"]:hover {background:#8881}
.st-key-sidebar-shell {height:calc(100dvh - 5rem);flex:0 0 calc(100dvh - 5rem);min-height:22rem;gap:.35rem;margin-top:-1.75rem}
.st-key-sidebar-shell > div:has(.st-key-sidebar-panels) {flex:1 1 0;min-height:0;overflow:hidden}
.st-key-sidebar-shell > div:has(.st-key-app-brand) {flex:0 0 auto}
.st-key-app-brand,.st-key-all-projects {flex:0 0 auto}
.st-key-app-brand [data-testid="stHorizontalBlock"],.st-key-sidebar-project-label [data-testid="stHorizontalBlock"] {flex-wrap:nowrap}
.st-key-app-brand [data-testid="stColumn"],.st-key-sidebar-project-label [data-testid="stColumn"] {min-width:0}
.st-key-app-brand [data-testid="stColumn"]:first-child,.st-key-sidebar-project-label [data-testid="stColumn"]:first-child {flex:1 1 0;width:auto}
.st-key-app-brand [data-testid="stColumn"]:not(:first-child),.st-key-sidebar-project-label [data-testid="stColumn"]:not(:first-child) {flex:0 0 2.25rem;min-width:2.25rem;width:2.25rem}

.st-key-app-brand {gap:0}.st-key-app-brand h3 {padding:.2rem 0 .4rem;margin:0}
.st-key-app-brand div:has(> h3) {margin-bottom:0}
.st-key-settings-open button,.st-key-find-task button {min-width:2.25rem;min-height:2.25rem;padding:.25rem}
.st-key-settings-open button [data-testid="stIconMaterial"],.st-key-find-task button [data-testid="stIconMaterial"] {font-size:1.4rem}
.st-key-settings-open button [data-testid="stMarkdownContainer"],.st-key-find-task button [data-testid="stMarkdownContainer"] {position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
.st-key-sidebar-panels {height:100%;min-height:0;gap:0;flex:1 1 0}
.st-key-sidebar-panels > div:has(.st-key-sidebar-projects) {flex:0 0 var(--brofessor-project-share,50%);min-height:0;overflow:hidden}
.st-key-sidebar-panels > div:has(.st-key-sidebar-recents) {flex:1 1 0;min-height:0;overflow:hidden}
.st-key-sidebar-panels > div:has(.st-key-sidebar-splitter) {flex:0 0 14px;min-height:14px}
.st-key-sidebar-splitter {height:14px;min-height:14px;gap:0}
.brofessor-sidebar-divider {height:14px;cursor:row-resize;touch-action:none;display:flex;align-items:center;justify-content:center;outline-offset:-2px}
.brofessor-sidebar-divider::after {content:"";height:3px;width:2.75rem;background:#8887;border-radius:2px}
.brofessor-sidebar-divider:hover::after,.brofessor-sidebar-divider:focus-visible::after {background:#2d5d9e;width:4rem}
.st-key-sidebar-projects {height:100%;min-height:0;gap:.2rem;overflow-y:auto}
.st-key-sidebar-projects [class*="st-key-sidebar-project-row-"] {position:relative;gap:0;--folder-row-height:2.25rem}
.st-key-sidebar-projects [class*="st-key-sidebar-project-row-"]:has([class*="st-key-folder-heading-active-"])::before {content:"";position:absolute;inset:0 0 auto;height:var(--folder-row-height);background:light-dark(#eaf0fb,#27364c);border-radius:.4rem;pointer-events:none}
.st-key-sidebar-projects [class*="st-key-folder-heading-"] {position:absolute;top:0;left:var(--folder-row-height);right:0;width:auto;height:var(--folder-row-height);z-index:1}
.st-key-sidebar-projects [class*="st-key-folder-toggle-"] summary {height:var(--folder-row-height);min-height:var(--folder-row-height);width:var(--folder-row-height);padding:0;background:transparent;border-radius:.4rem;justify-content:center}
.st-key-sidebar-projects [class*="st-key-folder-toggle-"] summary > span {gap:0;justify-content:center;width:100%}
.st-key-sidebar-projects [class*="st-key-folder-toggle-"] summary > span > div {flex:0 0 0;min-width:0;width:0}
.st-key-sidebar-projects [class*="st-key-folder-toggle-"] summary [data-testid="stMarkdownContainer"] {position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
.st-key-sidebar-projects details {border:0;background:transparent}
.st-key-sidebar-projects [data-testid="stExpanderDetails"] {padding:0 0 0 var(--folder-row-height);border:0}
.st-key-sidebar-projects [data-testid="stExpanderDetails"] > [data-testid="stVerticalBlock"] {gap:.1rem}
.st-key-sidebar-projects summary p {overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.st-key-sidebar-projects button,.st-key-sidebar-recents button {width:100%;min-height:2rem;padding:.2rem .45rem;text-align:left;justify-content:flex-start;border:0;background:transparent}
.st-key-sidebar-projects button div,.st-key-sidebar-recents button div {justify-content:flex-start}
.st-key-sidebar-projects button > div,.st-key-sidebar-recents button > div {width:100%}
.st-key-sidebar-projects button p,.st-key-sidebar-recents button p {text-align:left;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.st-key-sidebar-projects [class*="st-key-folder-heading-"] button {height:var(--folder-row-height);min-height:var(--folder-row-height);padding:0 .5rem}
.st-key-sidebar-projects [class*="st-key-folder-heading-"] button > div > span {width:100%;min-width:0}
.st-key-sidebar-projects [class*="st-key-folder-heading-"] button > div > span > span:first-child {flex-shrink:0}
.st-key-sidebar-projects [class*="st-key-folder-heading-"] [data-testid="stMarkdownContainer"] {flex:1 1 auto;min-width:0}
[class*="st-key-sidebar-project-children-"] {gap:.1rem}
.st-key-sidebar-recents {border-top:1px solid #8885;padding:.6rem .25rem .25rem;background:light-dark(#f3f5f8,#1c2230);border-radius:.4rem;box-sizing:border-box;height:100%;flex:1 1 auto;min-height:0;overflow-y:auto;gap:.2rem}
.st-key-sidebar-recents > div {flex:0 0 auto}
.st-key-sidebar-recents-heading {padding-bottom:.25rem}
.st-key-sidebar-recents-heading [data-testid="stMarkdownContainer"] {margin-bottom:0}
.st-key-sidebar-recents [class*="st-key-recent-task-"],.st-key-active-task {gap:.15rem;flex:0 0 auto}
.st-key-sidebar-recents [data-testid="stCaptionContainer"] {margin-bottom:0}.st-key-sidebar-recents [data-testid="stCaptionContainer"] p {font-size:.8rem;line-height:1.3}.st-key-sidebar-recents p {margin-bottom:0}
.st-key-active-task {background:light-dark(#eaf0fb,#27364c);border-radius:.4rem}

[class*="st-key-script-pager-"] {gap:.25rem;flex-wrap:nowrap}
[class*="st-key-script-pager-"] > div {flex:0 0 auto;width:auto}
[class*="st-key-script-pager-"] > div:has([data-testid="stSelectbox"]) {flex:0 0 7rem;width:7rem;font-variant-numeric:tabular-nums}
[class*="st-key-script-pager-"] [data-testid="stButton"] button {height:2.5rem;min-height:2.5rem;width:2.5rem;min-width:2.5rem;padding:0}
[class*="st-key-script-pager-"] [data-testid="stButton"] [data-testid="stMarkdownContainer"] {position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
.brofessor-stage {display:flex;gap:.75rem;justify-content:space-between;padding:.35rem 0;border-bottom:1px solid #8882}
.brofessor-stage small {color:inherit;opacity:.7}.brofessor-stage time {font-variant-numeric:tabular-nums;white-space:nowrap}
.brofessor-stage.running {font-weight:600}
.brofessor-stage.pending,.brofessor-stage.skipped {opacity:.65}
.st-key-project-heading-row {flex-wrap:wrap}
.st-key-project-heading-row > div:has(h1) {min-width:0;flex:1 1 16rem}
.st-key-project-heading-row h1 {overflow-wrap:anywhere}
@media(max-width:640px) {.brofessor-stage{flex-direction:column;gap:.1rem}.st-key-project-heading-row{gap:.5rem}}

/* Shared roles for pages, sections, content headings, labels, and metadata. */
:root {--brofessor-space-sm:.5rem;--brofessor-space-md:.75rem;--brofessor-space-lg:1.5rem}
:is([data-testid="stMainBlockContainer"],[data-testid="stDialog"]) :is(h1,h2,h3,h4) {color:inherit;font-weight:600;line-height:1.3;margin:0;padding:0;overflow-wrap:anywhere}
:is([data-testid="stMainBlockContainer"],[data-testid="stDialog"]) h1 {font-size:2rem}
:is([data-testid="stMainBlockContainer"],[data-testid="stDialog"]) h2 {font-size:1.5rem}
:is([data-testid="stMainBlockContainer"],[data-testid="stDialog"]) h3 {font-size:1.25rem}
:is([data-testid="stMainBlockContainer"],[data-testid="stDialog"]) h4 {font-size:1.0625rem}
[data-testid="stDialog"] [role="dialog"] > h2 {padding:1.25rem 3.5rem .25rem 1.5rem}
:is([data-testid="stMainBlockContainer"],[data-testid="stDialog"]) div:has(> :is(h1,h2,h3,h4)) {margin-bottom:0}
:is([data-testid="stMainBlockContainer"],[data-testid="stDialog"]) [data-testid="stMarkdownContainer"]:has([data-testid="stHeadingWithActionElements"]) {margin-bottom:0}
:is([data-testid="stMainBlockContainer"],[data-testid="stDialog"]) [data-testid="stCaptionContainer"] {margin-bottom:0;color:inherit;opacity:.82}
:is([data-testid="stMainBlockContainer"],[data-testid="stDialog"]) [data-testid="stCaptionContainer"] p {font-size:.875rem;line-height:1.45;color:inherit;margin-bottom:0}
:is([data-testid="stMainBlockContainer"],[data-testid="stDialog"]) [data-testid="stWidgetLabel"] p {font-size:.875rem;font-weight:500;color:inherit;line-height:1.4}
:is([data-testid="stMainBlockContainer"],[data-testid="stDialog"]) summary [data-testid="stMarkdownContainer"] p {font-size:1rem;font-weight:600;color:inherit;line-height:1.5}
.st-key-project-header {gap:var(--brofessor-space-sm)}
.st-key-result-detail {gap:var(--brofessor-space-lg)}
.st-key-task-heading {flex-wrap:nowrap;gap:var(--brofessor-space-sm)}
.st-key-task-heading > div:has(h2) {flex:1 1 0;min-width:0}
.st-key-result-output,.st-key-result-draft {gap:var(--brofessor-space-md)}
[class*="st-key-section-"] {border-top:1px solid #8885;padding-top:var(--brofessor-space-lg);gap:var(--brofessor-space-md)}
[class*="st-key-major-"] > [data-testid="stExpander"] > details {border:0;border-radius:0;background:transparent}
[class*="st-key-major-"] > [data-testid="stExpander"] > details > summary {padding:.25rem 0 .75rem}
[class*="st-key-major-"] > [data-testid="stExpander"] > details > summary [data-testid="stMarkdownContainer"] p {font-size:1.25rem;font-weight:600;line-height:1.3}
[class*="st-key-major-"] > [data-testid="stExpander"] > details > [data-testid="stExpanderDetails"] {padding:.25rem 0 .5rem}
.st-key-task-utilities {border-top:1px solid #8886;padding-top:var(--brofessor-space-lg);gap:var(--brofessor-space-sm)}
.st-key-task-utilities [class*="st-key-section-"] {padding-top:1rem}
.brofessor-rule {border:0;border-top:1px solid #8885;margin:.25rem 0}
.st-key-settings-content {max-height:calc(100dvh - 17rem);min-height:0;overflow-y:auto;padding-right:.25rem;gap:.75rem}
.st-key-settings-actions {border-top:1px solid #8885;padding-top:.75rem}
.st-key-sidebar-project-label h3 {font-size:1rem;line-height:1.4;padding:0;margin:0;color:inherit}
.st-key-sidebar-project-label [data-testid="stMarkdownContainer"] {margin-bottom:0}
.st-key-task-details {gap:var(--brofessor-space-md)}
.st-key-task-catalogue [class*="st-key-search-project-heading-"] button p {font-size:1.25rem;font-weight:600}
.brofessor-origin {font-size:.875rem;font-weight:600;color:inherit;margin:0}
@media(max-width:640px) {:is([data-testid="stMainBlockContainer"],[data-testid="stDialog"]) h1{font-size:1.875rem}.st-key-task-heading{align-items:flex-start}}
</style>"""


section_roles = st.components.v2.component(
    "brofessor_section_roles",
    js=files("brofessor.interfaces.web")
    .joinpath("assets", "section_roles.js")
    .read_text(encoding="utf-8"),
)


def apply():
    st.html(STYLES)
    section_roles(key="section-roles", height=0)


def heading(text, *, level=3):
    """Use native page/section headings and literal text for nested source titles."""
    if level == 4:
        st.html(f"<h4>{html.escape(str(text))}</h4>")
    else:
        {1: st.title, 2: st.header, 3: st.subheader}[level](text, anchor=False)


def origin(text):
    st.html(f'<p class="brofessor-origin">{html.escape(str(text))}</p>')


def rule():
    """A compact semantic separator for groups inside dialogs."""
    st.html('<hr class="brofessor-rule">')


@contextmanager
def section(label, key, *, expanded=False):
    """A native disclosure with a section-sized title and a visible boundary.

    Render its children even when closed: disclosure never controls widget or job
    lifetime. A stable key preserves the browser's choice across progress reruns.
    """
    initial = st.session_state.setdefault(SECTION_DEFAULT_PREFIX + key, expanded)
    with st.container(key="section-" + key):
        area = st.expander(label, key="major-" + key, expanded=initial)
        with area:
            yield area
