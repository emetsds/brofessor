"""Local Streamlit client. Durable work never lives in session_state."""

import argparse
import hashlib
import json
import tempfile
import uuid
from pathlib import Path

import streamlit as st

from brofessor import service
from brofessor.workspace import Workspace

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--workspace", default=".brofessor/workspace")
args, _ = parser.parse_known_args()
st.set_page_config(page_title="brofessor", page_icon="🎙", layout="wide")
st.title("brofessor")

with st.sidebar:
    workspace_path = st.text_input("Каталог материалов", args.workspace)
    provider = st.selectbox("Исполнитель", ["codex", "claude", "ollama"])
    model = st.text_input("Модель (пусто - выбор исполнителя)") or None
    st.caption(
        "Codex и Claude отправляют выбранный текст своему провайдеру. Ollama и речь работают локально."
    )
    if st.button("Проверить подключение"):
        from brofessor.executors import doctor

        try:
            st.json(doctor(provider, model))
        except Exception as error:
            st.error(str(error))

try:
    workspace = Workspace(workspace_path)
except Exception as error:
    st.error(str(error))
    st.stop()

sources_tab, create_tab, results_tab = st.tabs(["Источники", "Создать", "Задания и результаты"])

with sources_tab:
    uploaded = st.file_uploader(
        "Добавить материалы",
        type=["pdf", "epub", "md", "txt"],
        accept_multiple_files=True,
        max_upload_size=100,
    )
    if st.button("Импортировать", disabled=not uploaded):
        for upload in uploaded:
            try:
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / Path(upload.name).name
                    path.write_bytes(upload.getvalue())
                    workspace.add_source(path)
                st.success(f"Добавлен {upload.name}")
            except Exception as error:
                st.error(f"{upload.name}: {error}")
    for source in workspace.sources():
        with st.expander(source["name"]):
            units = workspace.units([source["id"]])
            ready = sum(u["status"] == "ready" for u in units)
            st.caption(f"Читаемых фрагментов: {ready}/{len(units)} · {source['id']}")
            for unit in units:
                st.markdown(f"**{unit['locator']}** · `{unit['id']}`")
                st.text(unit["text"] or "Текст не извлечён")
    query = st.text_input("Поиск по тексту")
    if query:
        from brofessor.sources import search_units

        for unit in search_units(workspace.units(), query):
            st.write(f"{unit['locator']} · {unit['id']}")
            st.text(unit["text"])

with create_tab:
    all_sources = workspace.sources()
    names = {s["id"]: s["name"] for s in all_sources}
    selected = st.multiselect(
        "Источники", list(names), default=list(names), format_func=lambda value: names[value]
    )
    if "request_key" not in st.session_state:
        st.session_state.request_key = uuid.uuid4().hex
    with st.form("create"):
        kind_label = st.selectbox("Результат", ["Подкаст", "Презентация", "Ответ на вопрос"])
        focus = st.text_area("На чём сосредоточиться / вопрос")
        language = st.selectbox("Язык", ["ru", "en"])
        minutes = st.select_slider("Длительность подкаста, минут", [3, 20, 30, 45, 60], value=20)
        st.caption("3 минуты - короткая проба голоса и сценария. Основные выпуски: 20–60 минут.")
        slide_count = st.number_input("Количество слайдов", 1, 40, 8)
        submitted = st.form_submit_button("Подготовить", disabled=not selected)
    if submitted:
        kind = {"Подкаст": "podcast", "Презентация": "slides", "Ответ на вопрос": "ask"}[kind_label]
        try:
            fingerprint = hashlib.sha256(
                json.dumps(
                    [
                        str(workspace.path),
                        kind,
                        selected,
                        focus,
                        language,
                        provider,
                        model,
                        minutes,
                        slide_count,
                    ],
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
            if st.session_state.get("request_fingerprint") != fingerprint:
                st.session_state.request_key = uuid.uuid4().hex
                st.session_state.request_fingerprint = fingerprint
            job = service.submit(
                workspace,
                kind,
                source_ids=selected,
                focus=focus,
                language=language,
                provider=provider,
                model=model,
                minutes=minutes,
                slide_count=slide_count,
                request_key=st.session_state.request_key,
            )
            st.success(f"Задание {job['id']} запущено. Результат появится во вкладке заданий.")
        except Exception as error:
            st.error(str(error))


@st.fragment(run_every=2)
def results():
    from brofessor.worker import is_running

    running = is_running(workspace)
    st.caption("Фоновая обработка работает" if running else "Фоновая обработка не запущена")
    jobs = workspace.jobs()
    if not running and any(job["status"] in ("queued", "running") for job in jobs):
        if st.button("Восстановить обработку"):
            from brofessor.worker import ensure_worker

            ensure_worker(workspace)
            st.rerun(scope="fragment")
    if not jobs:
        st.info("Здесь появятся сценарии, ответы, аудио и презентации.")
    for job in jobs:
        kind_name = {
            "ask": "Ответ",
            "podcast": "Сценарий подкаста",
            "slides": "План слайдов",
            "render_podcast": "Аудио",
            "render_slides": "Презентация",
        }.get(job["kind"], job["kind"])
        status_name = {
            "queued": "В очереди",
            "running": "В работе",
            "succeeded": "Готово",
            "failed": "Ошибка",
            "cancelled": "Отменено",
            "interrupted": "Прервано",
        }[job["status"]]
        with st.expander(f"{kind_name} · {status_name} · {job['id']}"):
            progress = job["progress"]
            stage = {
                "reading": "Чтение источников",
                "script": "Подготовка сценария",
                "speech": "Озвучка",
                "draft_ready": "Черновик готов",
            }.get(progress.get("stage"))
            if stage:
                st.caption(stage)
            if progress.get("total"):
                completed, total = progress.get("completed", 0), progress["total"]
                st.progress(min(completed / total, 1.0), text=f"Готово {completed} из {total}")
            if job["error"]:
                st.error(job["error"])
            if job["status"] in ("queued", "running"):
                if st.button("Отменить", key=f"cancel-{job['id']}"):
                    workspace.cancel(job["id"])
                    st.rerun(scope="fragment")
            elif job["status"] in ("failed", "interrupted", "cancelled"):
                if st.button("Продолжить", key=f"resume-{job['id']}"):
                    from brofessor.worker import ensure_worker

                    workspace.resume(job["id"])
                    ensure_worker(workspace)
                    st.rerun(scope="fragment")
            draft = workspace.draft(job["id"])
            if draft:
                if job["kind"] == "ask":
                    st.write(draft["data"]["answer"])
                    for citation in draft["data"]["citations"]:
                        unit = next(
                            (
                                u
                                for u in workspace.units(job["params"]["source_ids"])
                                if u["id"] == citation
                            ),
                            None,
                        )
                        if unit:
                            st.caption(f"{citation} · {unit['locator']}")
                            st.text(unit["text"])
                editor_key = f"editor:{workspace.path}:{job['id']}"
                buffer_key = editor_key + ":text"
                if editor_key not in st.session_state:
                    st.session_state[editor_key] = draft["revision"]
                    st.session_state[buffer_key] = json.dumps(
                        draft["data"], ensure_ascii=False, indent=2
                    )
                loaded_revision = st.session_state[editor_key]
                if loaded_revision != draft["revision"]:
                    st.warning(
                        "Появилась новая версия. Ваши несохранённые правки остаются в редакторе."
                    )
                st.caption(
                    f"Редактируемая версия: {loaded_revision}. Актуальная: {draft['revision']}"
                )
                text = st.text_area("Содержимое (JSON)", height=260, key=buffer_key)

                def reload_draft(job_id=job["id"], revision_key=editor_key, text_key=buffer_key):
                    current = workspace.draft(job_id)
                    st.session_state[revision_key] = current["revision"]
                    st.session_state[text_key] = json.dumps(
                        current["data"], ensure_ascii=False, indent=2
                    )

                st.button(
                    "Загрузить актуальную версию", key=f"reload-{job['id']}", on_click=reload_draft
                )
                if st.button("Сохранить правки", key=f"save-{job['id']}"):
                    try:
                        saved = service.edit_draft(
                            workspace, job["id"], json.loads(text), loaded_revision
                        )
                        st.session_state[editor_key] = saved["revision"]
                        st.rerun(scope="fragment")
                    except (ValueError, TypeError) as error:
                        st.error(str(error))
                if job["kind"] in ("podcast", "slides"):
                    label = "Озвучить" if job["kind"] == "podcast" else "Собрать PPTX"
                    if st.button(label, key=f"render-{job['id']}"):
                        service.render(
                            workspace,
                            job["id"],
                            request_key=f"render:{job['id']}:{draft['revision']}",
                        )
                        st.rerun(scope="fragment")
            for artifact in workspace.artifacts(job["id"]):
                path = service.artifact_path(workspace, artifact["path"])
                if not path.exists():
                    st.error(f"Файл отсутствует: {path.name}")
                    continue
                if artifact["kind"] == "audio":
                    st.audio(str(path))
                metadata = artifact["metadata"]
                if metadata.get("duration_matches") is False:
                    actual = round(metadata["duration_seconds"])
                    target = round(metadata["requested_seconds"])
                    st.warning(
                        f"Получилось {actual // 60}:{actual % 60:02d} вместо "
                        f"{target // 60}:{target % 60:02d}. Длительность отличается более чем "
                        "на 10%. Скорректируйте сценарий перед следующей сборкой."
                    )
                elif metadata.get("warning"):
                    st.warning(metadata["warning"])
                st.download_button(
                    f"Скачать {path.name}",
                    path.read_bytes(),
                    file_name=path.name,
                    key=f"download-{job['id']}-{path.name}",
                )


with results_tab:
    results()
