# Основания технического плана

Проверено 01.11.2026. `read_scope`: целевые разделы официальной документации, README/model cards и справка установленных CLI. Репозитории поставщиков целиком не аудировались. Модельные вызовы, загрузка весов, авторизация и генерация аудио/слайдов в этой задаче не выполнялись.

## Локальная отправная точка

Целевой профиль пилота - Apple M4, 32 ГБ unified memory. В текущем окружении обнаружены Codex CLI 0.162.1, Claude Code 2.1.185, Ollama client 0.40.6, uv 0.11.7, Node 26.0.0 и системный Python 3.9.6. `ollama --version` сообщил, что не может подключиться к работающему экземпляру. Это не доказывает отсутствие службы вне доступного окружения.

Наличие бинарников не подтверждает подписку Claude, доступность моделей, достаточные квоты или работоспособность pipeline. Для разработки предложен изолированный Python 3.12 и отдельно проверенный стабильный Node. Глобальные настройки и установленное ПО не менялись.

## Первичные источники

| Источник | Проверенный факт и следствие для плана |
|---|---|
| [Agent Skills specification](https://agentskills.io/specification) | Переносимый каталог с `SKILL.md`, name и description. Стандарт формата не гарантирует одинаковые пути discovery и permissions всех клиентов |
| [Codex skills](https://learn.chatgpt.com/docs/build-skills) | Поддержаны skills, repo/user discovery в `.agents/skills` и symlinks. Общие инструкции можно отделить от клиентской установки |
| [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode) | `codex exec`, JSON events, финальный structured output и повторное использование CLI auth. Это основание для bounded runner, не для передачи subscription tokens стороннему backend |
| [Codex authentication](https://learn.chatgpt.com/docs/auth) | Подписочный вход и API key - разные пути доступа и учёта использования |
| [Claude Code skills](https://code.claude.com/docs/en/skills) | Документированы `.claude/skills`, symlinks и собственные расширения. Общий skill не должен зависеть от Claude-only полей |
| [Claude Code headless](https://code.claude.com/docs/en/headless) | `claude -p`, структурированный вывод. `--bare` не читает подписочный OAuth/Keychain. Это также подтверждено локальным `claude --help` |
| [Claude CLI reference](https://code.claude.com/docs/en/cli-reference) | `--safe-mode` отключает пользовательские расширения, сохраняя обычную авторизацию. Вместе с ограничением tools это кандидат для runner, точное сочетание флагов требует smoke test |
| [Claude authentication](https://code.claude.com/docs/en/authentication) | Режим доступа определяется существующей авторизацией пользователя. ChatGPT Pro не предоставляет доступ к Claude |
| [Claude subscription usage](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) | Текущая справка описывает подписочное использование Claude Code/Agent SDK в рамках лимитов. Реальный аккаунт и способ запуска всё равно требуют проверки |
| [Claude API key precedence](https://support.claude.com/en/articles/12304248-manage-api-key-environment-variables-in-claude-code) | API key может изменить учёт расходов. Runner не должен незаметно менять подписочный профиль на API |
| [Claude credential boundaries](https://code.claude.com/docs/en/legal-and-compliance) | Официальный пользовательский CLI и сбор/посредничество OAuth credentials сторонним продуктом - разные способы интеграции |
| [Ollama chat](https://docs.ollama.com/api/chat) и [structured outputs](https://docs.ollama.com/capabilities/structured-outputs) | Local chat API принимает JSON schema. Правильная схема не гарантирует фактическую обоснованность |
| [Ollama local-only](https://docs.ollama.com/faq) | Есть `OLLAMA_NO_CLOUD=1`. Для local-only profile нужно проверять фактическую конфигурацию службы, а не только localhost URL |
| [Ollama compatibility](https://docs.ollama.com/api/openai-compatibility) | Поддерживается подмножество API. Другие compatible endpoints проверяются по capabilities |
| [Streamlit Session State](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state) | Состояние связано с браузерной сессией. Долговременный workspace/job state должен жить вне него |
| [Streamlit threading](https://docs.streamlit.io/develop/concepts/design/multithreading) | Пользовательские потоки имеют ограничения, фрагменты допускают периодическое обновление. Для долгих работ выбран отдельный процесс |
| [Streamlit uploader](https://docs.streamlit.io/develop/api-reference/widgets/st.file_uploader) и [audio](https://docs.streamlit.io/develop/api-reference/media/st.audio) | Есть загрузка источников и воспроизведение аудио. Имена файлов браузера нельзя прямо использовать как пути |
| [pypdf extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) | PDF не предоставляет надёжную семантическую структуру. Сканы и сложная вёрстка требуют отдельной обработки |
| [EPUB spine](https://www.w3.org/TR/epub-33/#sec-spine-elem) | Порядок чтения задаётся spine, а не сортировкой файлов |
| [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | Поддержаны RU/EN и управление голосом. Документация не подтверждает качество часового русского подкаста на целевом Mac |
| [Chatterbox](https://github.com/resemble-ai/chatterbox) и [MLX-Audio](https://github.com/Blaizzy/mlx-audio) | Альтернативный многоязычный TTS и runtime для Apple Silicon. Конкретные weights/версии/лицензии закрепляются в пилоте |
| [PptxGenJS](https://gitbrent.github.io/PptxGenJS/) | Создаёт текст, таблицы, схемы и charts в PPTX. Визуальное качество и редактируемость конкретного файла требуют проверки |
| [Google Office compatibility](https://support.google.com/docs/answer/6055139?hl=en) | PPTX можно открыть/конвертировать в Slides, но embedded charts могут стать изображениями |
| [Google Drive conversion](https://developers.google.com/workspace/drive/api/guides/manage-uploads#convert_a_file_to_a_different_type) | Есть программная конвертация PowerPoint в Google Slides через отдельно авторизованный API |
| [Pro API credits](https://developers.openai.com/api/docs/guides/chatgpt-api-credits) | Документация описывает отдельную активацию включённых кредитов для подходящих Pro-подписок. В аккаунте владельца это не проверено, поэтому не является обязательной зависимостью |

## Что остаётся проверить экспериментом

1. Реальные лимиты/авторизация bounded Codex и Claude runners, их поведение при отмене и malformed structured output.
2. Какая локальная текстовая модель достаточно хорошо выполняет RU/EN grounded tasks на 32 ГБ, с каким контекстом и скоростью.
3. Какая TTS даёт приемлемые ударения, стабильные два голоса и воспроизводимую длительную сборку. Скорость других Mac/GPU не считается замером целевого устройства.
4. Воспроизводимый рендер PPTX и правильные шрифты в чистой установке.
5. Поведение job worker при перезапуске Streamlit и одновременном управлении из CLI.
6. Достаточен ли простой локальный поиск для многосоставных и межъязыковых вопросов.

Даты и возможности поставщиков меняются. Перед реализацией конкретного адаптера повторно проверить только затронутую документацию и закрепить tested version. Проверка документов обосновывает план, но не равна успешному запуску интеграции.
