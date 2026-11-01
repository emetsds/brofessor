"""UI wording and the local user's language preference, independent of workspaces."""

from . import preferences

LANGUAGE_NAMES = {"ru": "Русский", "en": "English"}

# English messages are the identifiers; the UI calls text() with the same wording.
RUSSIAN = {
    "Requires WAV voice samples and transcripts. Weights are for noncommercial use.": "Нужны WAV-образцы голосов с расшифровками. Веса — для некоммерческого использования.",
    "Requires WAV voice samples and transcripts. Automatic stress is not included; use + when needed.": "Нужны WAV-образцы голосов с расшифровками. Автоматических ударений нет; при необходимости используйте +.",
    "Apple Silicon, f5 extra": "Apple Silicon, установка f5",
    "Requires a WAV voice sample and its transcript for each speaker. F5 weights are noncommercial; ESpeech uses manual stress marks when needed.": "Нужен WAV-образец голоса с расшифровкой для каждого ведущего. Веса F5 допускают некоммерческое использование; для ESpeech при необходимости размечайте ударения вручную.",
    "Set one WAV sample and its exact transcript for each speaker. Samples stay on this computer.": "Укажите WAV-образец и точную расшифровку для каждого ведущего. Образцы остаются на этом компьютере.",
    "Voice sample language": "Язык образцов голоса",
    "Voice sample: {role}": "Образец голоса: {role}",
    "Voice sample saved": "Образец голоса сохранён",
    "PCM16 WAV, 2–20 seconds": "PCM16 WAV, 2–20 секунд",
    "Exact transcript": "Точная расшифровка",
    "Save voice sample": "Сохранить образец голоса",
    "Speech models": "Модели озвучки",
    "Voice model": "Модель озвучки",
    "Voice model: {model}": "Модель озвучки: {model}",
    "Output language: {output_language}": "Язык результата: {output_language}",
    "Languages: {languages} · Download: {size} MB": "Языки: {languages} · Скачивание: {size} МБ",
    "Requirements: {requirements} · License: {license}": "Требования: {requirements} · Лицензия: {license}",
    "Apple Silicon, macOS, speech extra": "Apple Silicon, macOS, установка speech",
    "CPU, silero extra": "CPU, установка silero",
    "Russian only. No automatic stress: mark stressed vowels with + in the draft. Write numbers and Latin names as Russian words.": "Только русский. Нет автоматических ударений: отмечайте ударные гласные знаком + в черновике. Числа и латинские названия пишите русскими словами.",
    "The selected voice model does not support this draft's language.": "Выбранная модель озвучки не поддерживает язык этого черновика.",
    "Installed": "Установлена",
    "Not installed": "Не установлена",
    "Downloading model": "Скачивание модели",
    "Download model": "Скачать модель",
    "See job {id} in Jobs and results": "Задание {id} во вкладке «Задания и результаты»",
    "TTS model download": "Скачивание TTS-модели",
    "Downloaded {completed} of {total} MB": "Скачано {completed} из {total} МБ",
    "Download the selected voice model before generating audio.": "Скачайте выбранную модель озвучки перед созданием аудио.",
    "Project": "Проект",
    "Create or open a project": "Создать или открыть проект",
    "Project name": "Название проекта",
    "Projects folder": "Папка проектов",
    "Create project": "Создать проект",
    "Existing project folder": "Папка существующего проекта",
    "Open project": "Открыть проект",
    "Create a project or open an existing project folder to get started.": "Создайте проект или откройте папку существующего проекта, чтобы начать работу.",
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


def load_language(browser_locale: str | None = None) -> str:
    language = preferences.read().get("ui_language")
    if isinstance(language, str) and language in LANGUAGE_NAMES:
        return language
    return "ru" if not browser_locale or browser_locale.lower().startswith("ru") else "en"


def save_language(language: str) -> None:
    if language not in LANGUAGE_NAMES:
        raise ValueError("UI language must be ru or en")
    preferences.update(ui_language=language)
