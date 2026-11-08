# Промпты brofessor: чтение, редактура и предпросмотр

Это оглавление всех инструкций, которыми управляет brofessor: UTF-8 шаблоны `.md`, включая общие правила runner, агента, повторной навигации, отдельные developer-пробы. Файл содержит именно отправляемый текст или явно обозначенную общую часть. Заголовок, назначение, схема и связи находятся здесь и в `catalogue.json`, чтобы не попадать в запрос модели.

## С чего начать

Для оценки обычных ответов откройте [общие правила](common/materials.md), [границу исполнителя](common/runner.md) и [ответ с цитатами](questions/answer.md). Для отчётов — [общий формат](reports/write.md) и один из четырёх файлов [comparison](reports/comparison.md), [guide](reports/guide.md), [reference](reports/reference.md), [arguments](reports/arguments.md). Для подкаста по оригиналам — [план](podcasts/originals_outline.md) и [раздел](podcasts/originals_section.md); для книги — [перевод](books/translate.md), [словарь](books/glossary.md) и [привязки](books/align_translation.md).

Из корня репозитория:

```sh
uv run --no-sync brofessor prompts list
uv run --no-sync brofessor prompts show questions/answer
uv run --no-sync brofessor prompts preview questions/answer
uv run --no-sync brofessor prompts preview reports/guide --provider ollama
uv run --no-sync brofessor prompts preview --all > /tmp/brofessor-prompts.json
```

Команды не вызывают модели, shell-инструменты агента или сеть. `preview` показывает компонент, подставленные значения, общую сборку и полные сообщения с runner-границей. Для Codex/Claude это один stdin-текст; для Ollama — отдельные `system` и `user`. Общие части показаны в составе соответствующей операции, у `common/runner` — сама граница с пустым пользовательским сообщением. Поля `purpose`, `schema`, `versions` и `uses` описывают назначение и связи. Описание `navigation/retrieve` регистрируется как SDK-метаданные: собственный bounded-запрос передаёт инструкции и историю, а не отдельный список SDK tools.

По умолчанию входы короткие и синтетические. Это возможность прочитать фактически собираемые инструкции, не оценка качества ответа и не генерация по материалам проекта. Для своих входов передайте JSON-объект переменных через `--variables PATH`. Должны присутствовать все используемые переменные; пропуски и опечатки дают ошибку. Сложные JSON-значения сериализуются с теми же `ensure_ascii=False`, что и в workflow. Например:

```json
{"base": "ORIGINAL EVIDENCE: [{\"id\":\"demo:1\",\"text\":\"Only one test was run.\"}]"}
```

```sh
uv run --no-sync brofessor prompts preview questions/answer --variables /tmp/answer-inputs.json
```

Для просмотра шаблонов сохранённого задания:

```sh
uv run --no-sync brofessor -w /path/to/project prompts preview questions/answer --job JOB_ID
uv run --no-sync brofessor -w /path/to/project prompts show questions/answer --job JOB_ID
```

`--job` выбирает закреплённый набор инструкций; примерные входы остаются синтетическими, если не переданы `--variables`. Это не реконструкция всех прошлых запросов с исходными материалами. `show --job` выводит точный сохранённый шаблон без подстановок. В результате предпросмотра явно указаны `source`, SHA-256 набора и текущий путь редактируемого файла.

## Как редактировать

1. Измените нужный `.md`. Тексты оставлены на исходном английском: при выделении формулировки не переписывались. Новые строки и пробелы значимы. Для удобства чтения длинных исходных абзацев используйте перенос строк по ширине окна редактора.
2. Сохраните подстановки вида `{{language}}`, `{{base}}`, `{{payload}}` из колонки переменных. Можно удалить ненужную подстановку, оставив остальной текст; добавить неизвестное имя без изменения Python-конструктора нельзя. Файлы не исполняют Python, Jinja или выражения. Вставка выполняется один раз: скобки и похожие инструкции внутри исходных данных остаются данными. В шаблоне можно писать буквальные JSON-примеры.
3. Проверьте выбранный вариант командой `prompts preview ID`, затем весь каталог через `--all`. Сравнивайте `messages`, а не только компонент: общие правила и данные могут находиться в других частях.
4. Создайте **новое задание** или явно выберите регенерацию. Изменения `.md` читаются без перезапуска worker, но уже созданное задание сохраняет свои инструкции. Повтор с тем же request key и Resume продолжают прежний вариант. Новый follow-up, эпизод, сверка или исправление термина получают актуальные инструкции при создании собственного задания.

В editable checkout правится этот `src/brofessor/prompts/`. Для установленного wheel `prompts list` показывает реальный путь в установленном пакете; поддерживаемый путь изменения — исправить исходник, пересобрать wheel и переустановить его. Обновление установки может перезаписать ручные правки в `site-packages`.

Схемы результатов, сбор исходных фрагментов, JSON-сериализация, бюджеты, расчёт числа слов, допустимые citations и валидация остаются в Python. Редактирование промпта меняет смысловую инструкцию, а не эти контракты. Данные пользователя, WAV-референсы и их транскрипты не являются шаблонами: речевые адаптеры передают текст озвучки и референсные данные без дополнительных авторских system/instruction-промптов. Сообщения об ошибках файловой системы и типовые ошибки валидации SDK также остаются диагностическими данными; явные подсказки повторной навигации вынесены ниже.

## История и воспроизводимость

При создании текстового задания в существующих `params` сохраняется `prompt_snapshot`: полный применимый набор текстов, SHA-256 каждого файла и всего набора. Сохраняется семейство шаблонов с поддерживаемыми условными ветками; это не журнал фактически выполненных обращений. Никаких новых таблиц или сервисов нет. Во время исполнения весь workflow, включая asyncio/thread-переход runner, использует этот набор. Хеширование новых checkpoints включает фактические сообщения и общую границу runner.

Задания без `prompt_snapshot` и прежние версии workflow не поддерживаются. Для новой обработки создайте задачу заново; сохранённые результаты и авторские правки остаются на диске.

Проверка после редактуры:

```sh
uv run --no-sync brofessor prompts preview --all > /tmp/brofessor-prompts.json
uv run --no-sync pytest tests/prompts -q
```

Тесты защищают однократную подстановку, ошибки входов, framing, snapshot/retry/resume и сохранность редакций. Содержательное качество ответов проверяется отдельно. Для качества нужна отдельная проба на выбранных материалах.

## Каталог

Во всех строках действует общая [граница runner](common/runner.md). `base` — уже собранные общие правила и evidence; `instructions` — общие правила без evidence; `payload`, `agent`, `evidence`, `scope`, `glossary`, `occurrences`, `outline`, `section`, `plan`, `handoff`, `turns`, `first_version` — сериализованные данные соответствующего шага. `previous` — конец принятого диалога. Числовые переменные рассчитывает workflow. `task`, `word_instruction`, `correction_instruction`, `conversation_rule`, `translation`, `metalinguistic`, `header`, `prompt` связывают явно перечисленные ниже компоненты.

### Общие правила

| Файл | Назначение и связи | Переменные | Выходная схема / условие |
|---|---|---|---|
| [common/coverage](common/coverage.md) | Проверенные host сведения о полноте чтения; не evidence содержания | `verification` | `Схема автора материала`; Навигация с verification |
| [common/evidence](common/evidence.md) | Присоединение сериализованных evidence к общим правилам Общие части: [common/materials](common/materials.md), [common/coverage](common/coverage.md). | `instructions`, `evidence` | `Схема автора материала`; Все версии обычных материалов |
| [common/materials](common/materials.md) | Общие правила evidence, языка и пользовательского фокуса | `language`, `language_name`, `focus` | `Схема автора материала`; Все версии обычных материалов |
| [common/runner](common/runner.md) | Общая граница Codex, Claude и Ollama; добавляется к каждому запросу | — | `Схема конкретной операции`; Все текстовые обращения |

### Навигация по оригиналам

| Файл | Назначение и связи | Переменные | Выходная схема / условие |
|---|---|---|---|
| [navigation/agent](navigation/agent.md) | Инструкции агента выбора и чтения оригинальных документов | — | `NavigationStep`; Каталоги документов |
| [navigation/heading_hint](navigation/heading_hint.md) | Подсказка выбрать fragment offset при неоднозначном заголовке | — | `NavigationStep`; Каталоги документов; feedback |
| [navigation/narrow_tool](navigation/narrow_tool.md) | Подсказка уменьшить область или limit слишком большого результата | — | `NavigationStep`; Каталоги документов; retry |
| [navigation/read_candidates](navigation/read_candidates.md) | Подсказка повторить чтение после преждевременного finish по поиску | — | `NavigationStep`; Каталоги документов; retry |
| [navigation/read_scope](navigation/read_scope.md) | Подсказка дочитать заданную полную область | — | `NavigationStep`; Каталоги документов; retry |
| [navigation/retrieve](navigation/retrieve.md) | Описание инструмента для SDK; метаданные, не отдельное сообщение runner | — | `NavigationStep`; Каталоги документов |
| [navigation/selection_hint](navigation/selection_hint.md) | Подсказка сузить запрос при переполнении выбранного контекста | — | `NavigationStep`; Каталоги документов; feedback |
| [navigation/step](navigation/step.md) | Запрос одного типизированного шага через bounded runner Общие части: [navigation/agent](navigation/agent.md), [navigation/read_candidates](navigation/read_candidates.md), [navigation/read_scope](navigation/read_scope.md), [navigation/narrow_tool](navigation/narrow_tool.md), [navigation/heading_hint](navigation/heading_hint.md), [navigation/selection_hint](navigation/selection_hint.md). | `agent` | `NavigationStep`; Каталоги документов |

### Чтение и сжатие

| Файл | Назначение и связи | Переменные | Выходная схема / условие |
|---|---|---|---|
| [reading/fragments](reading/fragments.md) | Чтение каждого исходного фрагмента в отдельную заметку | `payload` | `ReadingBatch`; Текущее чтение |
| [reading/reduce](reading/reduce.md) | Сжатие заметок с раздельными ссылками на каждый оригинал | `payload` | `SectionNotes`; Текущее чтение |

### Вопросы и поиск

| Файл | Назначение и связи | Переменные | Выходная схема / условие |
|---|---|---|---|
| [questions/answer](questions/answer.md) | Ответ с точными оригинальными цитатами и статусом доказательств Общие части: [common/materials](common/materials.md), [common/evidence](common/evidence.md), [questions/conversation](questions/conversation.md). | `base` | `Answer`; ask |
| [questions/conversation](questions/conversation.md) | Ограничения использования прежних вопросов и ответов | `conversation` | `Answer`; Follow-up |
| [questions/search](questions/search.md) | Варианты лексического поиска по большим наборам оригиналов Общие части: [questions/search_conversation](questions/search_conversation.md). | `conversation_rule`, `payload` | `SearchQueries`; Превышен прямой контекст |
| [questions/search_conversation](questions/search_conversation.md) | Правило трактовки follow-up при поиске | — | `SearchQueries`; Поиск с conversation |

### Письменные отчёты

| Файл | Назначение и связи | Переменные | Выходная схема / условие |
|---|---|---|---|
| [reports/arguments](reports/arguments.md) | Задача разбора аргументации | — | `Report`; template = arguments |
| [reports/comparison](reports/comparison.md) | Задача сравнения источников | — | `Report`; template = comparison |
| [reports/guide](reports/guide.md) | Задача практического руководства | — | `Report`; template = guide |
| [reports/reference](reports/reference.md) | Задача тематического справочника | — | `Report`; template = reference |
| [reports/scope](reports/scope.md) | Область отобранных оригиналов и ограничения полноты | `base`, `scope` | `Report`; Все четыре template |
| [reports/terminology](reports/terminology.md) | Принятые термины конкретной редакции перевода | `glossary` | `Report`; report с terminology |
| [reports/write](reports/write.md) | Общий формат отчёта, атрибуция, цитаты и статус доказательств Общие части: [common/materials](common/materials.md), [common/evidence](common/evidence.md), [reports/scope](reports/scope.md), [reports/terminology](reports/terminology.md), [reports/comparison](reports/comparison.md), [reports/guide](reports/guide.md), [reports/reference](reports/reference.md), [reports/arguments](reports/arguments.md). | `base`, `task` | `Report`; Все четыре template |

### Презентации

| Файл | Назначение и связи | Переменные | Выходная схема / условие |
|---|---|---|---|
| [slides/create](slides/create.md) | Содержание слайдов, таблиц, последовательностей и speaker notes Общие части: [common/materials](common/materials.md), [common/evidence](common/evidence.md). | `base`, `slide_count` | `Slides`; slides |

### Подкасты и серии

| Файл | Назначение и связи | Переменные | Выходная схема / условие |
|---|---|---|---|
| [podcasts/check](podcasts/check.md) | Инструкции предметной сверки реплик с оригиналами | `language` | `CheckBatch`; check_podcast |
| [podcasts/check_packet](podcasts/check_packet.md) | Пакет реплик после правил сверки; префикс перед ORIGINALS Общие части: [podcasts/check](podcasts/check.md). | `header`, `turns` | `CheckBatch`; check_podcast |
| [podcasts/correct_originals](podcasts/correct_originals.md) | Коррекция раздела по оригиналам и его handoff; суффикс Общие части: [podcasts/originals_section](podcasts/originals_section.md). | `target`, `low`, `high`, `first_version` | `WrittenSection`; writing_method = originals |
| [podcasts/correct_section](podcasts/correct_section.md) | Одна коррекция длины и состава ведущих Общие части: [podcasts/section](podcasts/section.md), [podcasts/correction_range](podcasts/correction_range.md). | `prompt`, `count`, `target`, `correction_instruction`, `first_version` | `Podcast`; writing_method != originals |
| [podcasts/correction_range](podcasts/correction_range.md) | Числовые границы корректировки длины | `lower`, `upper` | `Podcast`; writing_method != originals; minutes >= 20 |
| [podcasts/originals_outline](podcasts/originals_outline.md) | Редакторский план с достаточностью источников и отношениями между ними Общие части: [common/materials](common/materials.md), [podcasts/voices](podcasts/voices.md), [podcasts/series_context](podcasts/series_context.md). | `instructions`, `evidence`, `minutes`, `target_words`, `lower`, `upper` | `EpisodePlan`; writing_method = originals |
| [podcasts/originals_section](podcasts/originals_section.md) | Раздел по оригиналам с редакторской памятью; префикс перед ORIGINALS Общие части: [common/materials](common/materials.md), [podcasts/voices](podcasts/voices.md), [podcasts/series_context](podcasts/series_context.md). | `instructions`, `plan`, `handoff`, `previous`, `section_number`, `sections`, `section`, `target`, `low`, `high`, `target_words`, `written` | `WrittenSection`; writing_method = originals |
| [podcasts/outline](podcasts/outline.md) | Равновесный план длинного выпуска Общие части: [common/materials](common/materials.md), [common/evidence](common/evidence.md), [podcasts/voices](podcasts/voices.md), [podcasts/series_context](podcasts/series_context.md). | `base`, `minutes`, `parts` | `Outline`; writing_method != originals; minutes >= 20 |
| [podcasts/section](podcasts/section.md) | Раздел выпуска по плану и концу предыдущего раздела Общие части: [common/materials](common/materials.md), [common/evidence](common/evidence.md), [podcasts/voices](podcasts/voices.md), [podcasts/series_context](podcasts/series_context.md), [podcasts/word_budget](podcasts/word_budget.md). | `base`, `outline`, `section_number`, `parts`, `section`, `word_instruction`, `previous` | `Podcast`; writing_method != originals; minutes >= 20 |
| [podcasts/series](podcasts/series.md) | План серии с распределением тем и общими терминами Общие части: [common/materials](common/materials.md), [common/evidence](common/evidence.md). | `base`, `count`, `minutes` | `Series`; podcast_series |
| [podcasts/series_context](podcasts/series_context.md) | Границы одного выпуска серии и общие термины | `series` | `Podcast`; Эпизод серии |
| [podcasts/short](podcasts/short.md) | Короткий диалог с последовательным продолжением Общие части: [common/materials](common/materials.md), [common/evidence](common/evidence.md), [podcasts/voices](podcasts/voices.md). | `base`, `part_number`, `parts`, `target_words`, `last_part`, `previous` | `Podcast`; minutes < 20 |
| [podcasts/voices](podcasts/voices.md) | Грамматический род ведущих и сохранение рода персонажей | — | `Podcast`; podcast |
| [podcasts/word_budget](podcasts/word_budget.md) | Остаток общего бюджета слов и границы раздела | `target_words`, `written`, `target`, `lower`, `upper` | `Podcast`; writing_method != originals; minutes >= 20 |

### Обучение

| Файл | Назначение и связи | Переменные | Выходная схема / условие |
|---|---|---|---|
| [studies/create](studies/create.md) | Вопросы на понимание, эталон ответа и критерии Общие части: [common/materials](common/materials.md), [common/evidence](common/evidence.md). | `base`, `count` | `StudySet`; study |
| [studies/review](studies/review.md) | Разбор сохранённых ответов ученика | `payload` | `FeedbackBatch`; review_study |

### Перевод и терминология

| Файл | Назначение и связи | Переменные | Выходная схема / условие |
|---|---|---|---|
| [books/align_translation](books/align_translation.md) | Перевод с привязкой каждого употребления термина к целевой фразе Общие части: [books/translate](books/translate.md), [books/metalinguistic](books/metalinguistic.md). | `translation`, `metalinguistic`, `occurrences` | `AlignedBatch`; translation_version = 4 |
| [books/glossary](books/glossary.md) | Извлечение значений терминов и исходных употреблений | `language`, `payload` | `GlossaryBatch`; translation_version = 4 |
| [books/metalinguistic](books/metalinguistic.md) | Сохранение исходного написания обсуждаемых слов | — | `AlignedBatch`; translation_version = 4 |
| [books/repair_alignment](books/repair_alignment.md) | Одна коррекция только отклонённых привязок без правки перевода | `payload` | `AlignmentBatch`; Версии с протоколом исправления привязок |
| [books/review_glossary](books/review_glossary.md) | Обзор пропущенных повторяющихся терминов | `payload` | `GlossaryReviewBatch`; translation_version = 4 |
| [books/revise_term](books/revise_term.md) | Изменение только целевых терминологических фраз | `payload` | `Replacements`; terminology_update |
| [books/translate](books/translate.md) | Полный перевод блоков с неизменяемыми inline-маркерами | `language`, `payload` | `TranslationBatch / AlignedBatch`; translation_version = 4; также локальная проба |

### Явные developer-пробы

| Файл | Назначение и связи | Переменные | Выходная схема / условие |
|---|---|---|---|
| [experiments/episode_materials](experiments/episode_materials.md) | Общие инструкции пробы сравнения авторов подкаста | `focus` | `Podcast`; Только явная developer-проба, не workflow продукта |
| [experiments/episode_outline](experiments/episode_outline.md) | План в пробе сравнения двух авторов Общие части: [experiments/episode_materials](experiments/episode_materials.md), [experiments/evidence](experiments/evidence.md). | `base` | `Outline`; Только явная developer-проба, не workflow продукта |
| [experiments/evidence](experiments/evidence.md) | Присоединение evidence в пробе сравнения Общие части: [experiments/episode_materials](experiments/episode_materials.md). | `instructions`, `evidence` | `Outline / Podcast`; Только явная developer-проба, не workflow продукта |
| [experiments/whole_xhtml](experiments/whole_xhtml.md) | Базовый опыт перевода XHTML целиком, без гарантий проекции | `payload` | `WholeDocuments`; Только явная developer-проба, не workflow продукта |

### Где определены выходные схемы

- [Answer, Podcast, Slides](../models.py).
- [NavigationStep](../features/sources/navigation.py), [SearchQueries](../features/questions.py).
- [ReadingBatch, SectionNotes, SectionNote](../features/sources/reading.py).
- [Report](../features/reports.py), [StudySet, FeedbackBatch](../features/studies.py).
- [Outline](../features/podcasts/writer.py), [EpisodePlan, WrittenSection](../features/podcasts/episode_writer.py), [Series](../features/podcasts/series.py), [CheckBatch](../features/podcasts/checks.py).
- [TranslationBatch](../infrastructure/formats/epub.py), [GlossaryBatch, GlossaryReviewBatch, AlignedBatch, AlignmentBatch, Replacements](../features/books/terminology.py).
- `WholeDocuments` — схема [локальной XHTML-пробы](../../../tools/probe_epub_translation.py) из checkout; developer tools в wheel не входят.

SDK и адаптеры по-прежнему получают эти схемы из Python. Codex/Claude дополнительно применяют прежнюю strict-schema адаптацию в runner. Условный выбор файлов и места вызова можно найти по `prompts.render` в исходниках и по полю `source` в `catalogue.json`.
