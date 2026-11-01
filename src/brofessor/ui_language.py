"""UI wording and the local user's language preference, independent of workspaces."""

import json
import os
import sys
import tempfile
from pathlib import Path

LANGUAGE_NAMES = {"ru": "Русский", "en": "English"}

# English messages are the identifiers; the UI calls text() with the same wording.
RUSSIAN = {
    "Workspace": "Каталог материалов",
    "Provider": "Исполнитель",
    "Model (leave empty for the provider default)": "Модель (пусто — выбор исполнителя)",
    "Ollama port": "Порт Ollama",
    "Port of the running Ollama server on 127.0.0.1.": "Порт уже запущенного сервера Ollama на 127.0.0.1.",
    "Codex and Claude send selected text to their providers. Ollama and speech run locally.": "Codex и Claude отправляют выбранный текст своему провайдеру. Ollama и речь работают локально.",
    "Check connection": "Проверить подключение",
    "Connection ready": "Подключение готово",
    "Connection unavailable": "Подключение недоступно",
    "Could not check the connection: {error}": "Не удалось проверить подключение: {error}",
    "Could not open the workspace: {error}": "Не удалось открыть каталог материалов: {error}",
    "Could not remember your language choice. It will apply only to this session.": "Не удалось запомнить язык. Выбор будет действовать только в этой сессии.",
    "Sources": "Источники",
    "Create": "Создать",
    "Jobs and results": "Задания и результаты",
    "Add materials": "Добавить материалы",
    "Import": "Импортировать",
    "Added {name}": "Добавлен {name}",
    "Could not import {name}: {error}": "Не удалось импортировать {name}: {error}",
    "Readable fragments: {ready}/{total} · {id}": "Читаемых фрагментов: {ready}/{total} · {id}",
    "No text extracted": "Текст не извлечён",
    "Search source text": "Поиск по тексту",
    "Output": "Результат",
    "Podcast": "Подкаст",
    "Presentation": "Презентация",
    "Answer a question": "Ответ на вопрос",
    "Focus / question": "На чём сосредоточиться / вопрос",
    "Output language": "Язык результата",
    "Podcast duration, minutes": "Длительность подкаста, минут",
    "3 minutes is a short script and voice preview. Full episodes: 20–60 minutes.": "3 минуты — короткая проба голоса и сценария. Основные выпуски: 20–60 минут.",
    "Number of slides": "Количество слайдов",
    "Prepare": "Подготовить",
    "Job {id} submitted. Find the result in Jobs and results.": "Задание {id} запущено. Результат появится во вкладке заданий.",
    "Could not submit the job: {error}": "Не удалось запустить задание: {error}",
    "Background processing is running": "Фоновая обработка работает",
    "Background processing is stopped": "Фоновая обработка не запущена",
    "Restore processing": "Восстановить обработку",
    "Scripts, answers, audio, and presentations will appear here.": "Здесь появятся сценарии, ответы, аудио и презентации.",
    "Answer": "Ответ",
    "Podcast script": "Сценарий подкаста",
    "Slide outline": "План слайдов",
    "Audio": "Аудио",
    "Queued": "В очереди",
    "Running": "В работе",
    "Ready": "Готово",
    "Failed": "Ошибка",
    "Cancelled": "Отменено",
    "Interrupted": "Прервано",
    "Reading sources": "Чтение источников",
    "Writing script": "Подготовка сценария",
    "Generating speech": "Озвучка",
    "Draft ready": "Черновик готов",
    "Completed {completed} of {total}": "Готово {completed} из {total}",
    "Details: {error}": "Подробности: {error}",
    "Cancel": "Отменить",
    "Resume": "Продолжить",
    "A newer revision is available. Your unsaved edits are still in the editor.": "Появилась новая версия. Ваши несохранённые правки остаются в редакторе.",
    "Editing revision: {loaded}. Latest: {latest}": "Редактируемая версия: {loaded}. Актуальная: {latest}",
    "Content (JSON)": "Содержимое (JSON)",
    "Load latest revision": "Загрузить актуальную версию",
    "Save edits": "Сохранить правки",
    "Could not save edits: {error}": "Не удалось сохранить правки: {error}",
    "Generate audio": "Озвучить",
    "Build PPTX": "Собрать PPTX",
    "File is missing: {name}": "Файл отсутствует: {name}",
    "Actual duration {actual}, target {target}. The difference exceeds 10%. Edit the script before rendering again.": "Получилось {actual} вместо {target}. Длительность отличается более чем на 10%. "
    "Скорректируйте сценарий перед следующей сборкой.",
    "Audio warning: {warning}": "Предупреждение по аудио: {warning}",
    "Download {name}": "Скачать {name}",
}


def text(language: str, message: str, **values) -> str:
    template = RUSSIAN[message] if language == "ru" else message
    return template.format(**values)


def preferences_path() -> Path:
    if configured := os.environ.get("XDG_CONFIG_HOME"):
        base = Path(configured).expanduser()
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    return base / "brofessor" / "preferences.json"


def _preferences() -> dict:
    try:
        value = json.loads(preferences_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def load_language(browser_locale: str | None = None) -> str:
    language = _preferences().get("ui_language")
    if isinstance(language, str) and language in LANGUAGE_NAMES:
        return language
    return "ru" if not browser_locale or browser_locale.lower().startswith("ru") else "en"


def save_language(language: str) -> None:
    if language not in LANGUAGE_NAMES:
        raise ValueError("UI language must be ru or en")
    path = preferences_path()
    value = {**_preferences(), "ui_language": language}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".preferences-", suffix=".json")
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
