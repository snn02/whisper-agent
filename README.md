# Локальный Whisper для проектов

Распознаёт аудио и видео в текущем проекте через одноразовый Docker-контейнер на NVIDIA GPU. MCP всегда использует официальную многоязычную модель `small`, язык по умолчанию — `ru`, задача — `transcribe`. Контейнер удаляется после каждой команды (`docker run --rm`); загруженные модели хранятся в томе `whisper-agent-models`. Каждая модель скачивается при первом использовании в этом томе. Полный текст попадает только в файлы результатов. Журнал JSONL содержит файлы, время, длительность, статус и ошибки.

## Требования

- Windows 11/10, Docker Desktop с WSL 2 и включённым GPU, Node.js 20+; для WSL нужны Node.js 20+ и доступ к Docker Desktop из обычного терминала.
- На RTX 5060 Laptop GPU уже проверены проброс GPU через Docker и `torch.cuda.is_available()` в рабочем образе. На другой машине повторите GPU-проверку установщиком или командой `node $Agent check` ниже.
- Достаточно места для крупного образа PyTorch/CUDA и модели `small`. Первый запуск скачает веса в Docker volume; без сети это не сработает.

Образ использует `openai-whisper==20250625`, `torch==2.13.0` и `torchaudio==2.11.1` из официального индекса `cu132`, `pyannote.audio==4.0.7` и `ffmpeg`. [Исходный Whisper](https://github.com/openai/whisper), [документация Docker Desktop GPU](https://docs.docker.com/desktop/features/gpu/).

Версия пакета `1.1.0` подготовлена к выпуску. Обновлённый образ собран; вычисление CUDA и импорт pyannote проверены на RTX 5060 Laptop GPU. Автономная установка навыка на Windows проверена. Сквозная диаризация с весами модели, полная установка сервиса и подключение приложений ещё требуют проверки; публикация релиза не выполнена.

## Что нужно запускать

| Компонент | Как запускается | Когда работает |
|---|---|---|
| Docker Desktop | Запустите приложение в Windows перед работой | Обеспечивает доступ к Docker и NVIDIA GPU |
| Локальный MCP (`node .../mcp.mjs`) | Codex, Claude Code, локальный Cowork или OpenCode запускает его при подключении | Принимает вызовы `list_media` и `transcribe_project` |
| Контейнер Whisper | MCP или CLI создаёт его автоматически | Выполняет поиск медиа, GPU-проверку или распознавание; затем удаляется |

Отдельную службу Whisper и MCP вручную запускать не нужно. Ручной запуск MCP нужен только для диагностики.

## Первый запуск на Windows

1. Запустите Docker Desktop и дождитесь его готовности. Откройте обычный Windows PowerShell и проверьте `docker version` и `node --version` (нужна версия Node.js 20 или новее).
2. Откройте PowerShell в каталоге этого репозитория и выполните установщик:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
   ```

3. Подключите MCP к агентам одной командой:

   ```powershell
   powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\WhisperAgent\connect-windows.ps1"
   ```

4. Перезапустите Codex, Claude Code или OpenCode и откройте новый локальный сеанс. В Codex проверьте подключение командой `codex mcp list` или через раздел **Settings → MCP servers**.
5. Попросите агента, например: «Найди медиа в `C:\Users\SAWA\Мой проект` и распознай их. Сохрани результаты в `C:\Users\SAWA\Мой проект\transcripts` в формате `txt`». Агент сначала вызовет `list_media`, затем `transcribe_project`. Если каталог или формат результата не заданы, он должен спросить вас до запуска.

Установщик спрашивает, куда установить автономный навык `name-speakers`: в проект (`project`), в общие навыки (`global`), в каталог конкретного агента (`custom`) либо пропустить (`skip`). Затем копирует runtime в `%LOCALAPPDATA%\WhisperAgent`, выполняет `npm ci`, собирает образ `whisper-agent:torch2.13-cu132` и проверяет `torch.cuda.is_available()` внутри контейнера. Первая сборка и первая загрузка модели могут занять много времени и требуют сети. Установщик не меняет настройки агентов, журналы и Docker volume. Если репозиторий находится в WSL, откройте его в Windows по пути `\\wsl.localhost\<имя-дистрибутива>\home\sawa\projects\whisper` либо скопируйте на Windows-диск.

Для автоматической установки используйте `-SkillScope project -SkillProjectDirectory 'C:\Мой проект'`, `-SkillScope global`, `-SkillScope custom -SkillsDirectory 'C:\путь\к\skills'` или `-SkillScope skip`. Проектный и общий варианты используют `.agents\skills`; если ваш агент читает другой каталог, выберите `custom`. Уже установленный навык не заменяется без `-OverwriteSkill`. Навык устанавливается отдельно до сборки и остаётся работоспособным, если установка сервиса завершилась ошибкой.

## Только навык назначения имён

Навык находится в [`skills/name-speakers`](skills/name-speakers/SKILL.md). Можно установить только его из репозитория: Docker, GPU, модели, `npm ci` и сам сервис не нужны. Он работает по команде пользователя с готовыми JSON, TXT, Markdown, SRT и VTT, содержащими `SpeakerN`, `SPEAKER_00` или аналогичные метки. Для других форматов нужен доступный агенту способ прочитать и сохранить файл.

Из корня репозитория (Node.js 20+):

```powershell
# Навык только для выбранного проекта
node scripts/install-skill.mjs --scope project --project-dir 'C:\Мой проект'
# Или общие навыки: ~/.agents/skills
node scripts/install-skill.mjs --scope global
# Или каталог навыков конкретного агента, например Claude Code
node scripts/install-skill.mjs --scope custom --skills-dir "$env:USERPROFILE\.claude\skills"
```

В WSL используйте абсолютный Linux-путь, например `--project-dir /home/sawa/projects/example`. Установщик использует только стандартную библиотеку Node. Для замены существующей установки явно добавьте `--overwrite`.

Без Node достаточно скопировать **всю папку** `skills/name-speakers` в каталог навыков агента. Если агент устанавливает навыки из Git-репозитория, укажите ему этот подкаталог и попросите установить только его. Ни установщик сервиса, ни корневые зависимости при этом запускать не нужно. Перезагрузите навыки или откройте новый сеанс агента.

Пример запроса: «Примени name-speakers к `meeting.srt`. На встрече были Саша, Алексей и Мария. Speaker2 — Алексей. Сохрани исправленную копию». Навык использует указания чата и относящийся к встрече контекст проекта, сохраняет исходные метки, отличает предположения от подтверждений и оставляет неизвестных как `SpeakerN`. Исходный файл сохраняется; рядом создаются исправленная копия и таблица назначений. Полный транскрипт в чат не выводится.

## Диаризация без назначения имён

Для разделения речи по участникам передайте MCP `diarize: true` или CLI `--diarize`. По умолчанию диаризация выключена. Сервис использует официальный Whisper `small` для текста и локальный `pyannote/speaker-diarization-community-1` для голосов; имена и список участников ему не передаются.

Перед первым использованием примите условия [модели на Hugging Face](https://huggingface.co/pyannote/speaker-diarization-community-1) и настройте `HF_TOKEN` в окружении процесса CLI/MCP с правом чтения модели. Для запуска из приложения агент должен унаследовать это окружение: после настройки переменной перезапустите приложение. Не передавайте токен параметром MCP или в тексте запроса. Docker получает переменную по имени, значение не записывается в исходники или журнал. Кэш хранится в `whisper-agent-models`; скачанные веса используются повторно. Телеметрия pyannote отключена в образе.

Токен создаётся в [Hugging Face → Settings → Access Tokens](https://huggingface.co/settings/tokens): `Create new token`, тип `Read`, например имя `whisper-local`. Права записи не нужны. В Windows нажмите **Win+R**, выполните `rundll32 sysdm.cpl,EditEnvironmentVariables` и создайте **переменную пользователя** `HF_TOKEN` со значением токена. Сам токен не вводите в чат или команды, сохраняемые в истории. Для WSL переменная настраивается отдельно в окружении запуска CLI/MCP. [Документация токенов](https://huggingface.co/docs/hub/security-tokens).

```powershell
$Agent = Join-Path $env:LOCALAPPDATA 'WhisperAgent\src\cli.mjs'
node $Agent list --project 'C:\Мой проект'
node $Agent transcribe --project 'C:\Мой проект' --output 'C:\Мой проект\transcripts' --format txt --diarize
```

Помимо выбранного обычного результата появится `transcript.diarized.json` в каталоге каждого медиа. Обычный TXT/SRT/JSON Whisper сохраняет прежний формат; **метки участников находятся в дополнительном JSON**, который можно передать навыку. Контракт описан в [docs/diarized-transcript.md](docs/diarized-transcript.md). Коллизия дополнительного файла тоже запрещает перезапись без `--overwrite`.

Метки устойчивы внутри одного результата, но не между встречами. При неоднозначной привязке слова `speaker_id` равен `null`. Перекрывающиеся голоса сохраняются в интервалах; это не разделение звуковой дорожки. При отсутствии GPU или сбое диаризации запрос не подменяется успешным результатом без диаризации.

### Прямой запуск без агента

Следующие команды позволяют проверить GPU, найти медиа и запустить распознавание вручную:

```powershell
$Agent = Join-Path $env:LOCALAPPDATA 'WhisperAgent\src\cli.mjs'
node $Agent check
node $Agent list --project 'C:\Users\SAWA\Мой проект'
node $Agent transcribe --project 'C:\Users\SAWA\Мой проект' --output 'C:\Users\SAWA\Мой проект\transcripts' --format txt
```

Последняя команда создаёт `transcripts\<относительный путь входного файла с расширением>\transcript.txt`. Например, `audio\call.mp3` и `audio\call.wav` попадают в разные каталоги. Если медиа нет или результат уже существует, команда возвращает ошибку; `--overwrite` разрешает замену только при вашем явном выборе. Поддерживаются `txt`, `srt`, `vtt`, `tsv`, `json`, `all`. Формат `json` содержит текст в файле результата; журнал никогда не содержит его. `all` сохраняет все пять форматов.

Для другой модели при **ручном** запуске CLI укажите `--model` и новый каталог результатов, чтобы не столкнуться с уже существующими файлами:

```powershell
node $Agent transcribe --project 'C:\Users\SAWA\Мой проект' --output 'C:\Users\SAWA\Мой проект\transcripts-medium' --format txt --model medium
```

Модель `medium` будет скачана при первом использовании. MCP не принимает модель, отличную от `small`; при таком параметре распознавание не начнётся.

Поиск рекурсивный: `wav`, `mp3`, `m4a`, `flac`, `ogg`, `opus`, `aac`, `wma`, `mp4`, `mov`, `mkv`, `webm`, `avi`. Пропускаются символические ссылки, `.git`, `node_modules`, `.venv`, `dist`, `build` и каталог результатов, если он находится внутри проекта. Проект монтируется в контейнер только для чтения; результат — отдельно для записи.

Журнал Windows: `%LOCALAPPDATA%\WhisperAgent\runs.jsonl`; переменная `WHISPER_LOG_PATH` переопределяет путь. Каждая строка — JSON одной попытки распознавания: входные файлы, выходные пути, длительности в миллисекундах, ошибки, модель, язык, образ. При сбое запуска Docker сохраняется запись с общей ошибкой и пустым списком файлов.

## Как проверить ход распознавания

MCP возвращает итог после обработки всех файлов и не сообщает промежуточный процент. Пока запрос выполняется, в PowerShell можно проверить, жив ли контейнер и использует ли он ресурсы:

```powershell
docker ps --filter ancestor=whisper-agent:torch2.13-cu132
$Container = docker ps -q --filter ancestor=whisper-agent:torch2.13-cu132
if ($Container) { docker stats --no-stream $Container }
```

Если контейнер виден в `docker ps`, запрос ещё выполняется. После завершения он удаляется, а итоговая запись появляется в журнале. Для одного уже обработанного файла результат может появиться раньше окончания всего запроса. Проверяйте **время** последней строки журнала: пока идёт новый запрос, там может оставаться предыдущий запуск.

```powershell
Get-Content "$env:LOCALAPPDATA\WhisperAgent\runs.jsonl" -Tail 1 |
  ConvertFrom-Json | Select-Object timestamp,status,model,total_duration_ms
```

Статус `success` означает, что все файлы обработаны, `partial` — что часть файлов завершилась с ошибкой, `error` — что результат получить не удалось. Полный текст ищите только в каталоге результатов.

## Подключение агентов Windows: подробности

Команда `connect-windows.ps1` из раздела первого запуска регистрирует локальный MCP в установленных Codex, Claude Code и OpenCode. Для Codex и OpenCode она задаёт часовой лимит; Claude Code использует свой стандартный лимит. Уже существующую запись `whisper-agent` скрипт не меняет. Если OpenCode хранит конфигурацию в JSONC или CLI приложения отсутствует, скрипт сообщает, что нужно подключить вручную. После подключения перезапустите Windows-приложения. Агент запускает MCP при подключении; контейнер Docker создаётся на запрос `list_media`, `transcribe_project` или GPU-проверку и удаляется после неё.

Чтобы запустить MCP вручную для диагностики, выполните `node "$env:LOCALAPPDATA\WhisperAgent\src\mcp.mjs"`. Процесс будет ожидать запросы MCP по stdin; отсутствие обычного вывода — ожидаемо. Ниже приведены ручные способы подключения, если автоматический скрипт пропустил приложение.

MCP-сервер запускается локально командой `node "%LOCALAPPDATA%\WhisperAgent\src\mcp.mjs"` (в конфигурации указывайте **развёрнутый абсолютный путь**, а не `%LOCALAPPDATA%`). Он предоставляет `list_media` и `transcribe_project`. Подключение не требует выдавать агентской командной песочнице доступ к Docker socket: Docker вызывает установленный локальный MCP-процесс.

В MCP модель закреплена как `small`: параметр `model` с другим значением отклоняется до запуска Docker. Если вы сами хотите применить другую модель, запускайте CLI вручную с `--model NAME`; агенту нельзя выбирать модель за вас.

**Codex.** В обычном Windows PowerShell:

```powershell
codex mcp add whisper-agent -- node "$env:LOCALAPPDATA\WhisperAgent\src\mcp.mjs"
codex mcp list
```

В настройке Codex MCP для долгих записей задайте `tool_timeout_sec = 3600` в секции `[mcp_servers.whisper-agent]` файла `~/.codex/config.toml`. [Документация Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

**Claude Code (включая вкладку Code приложения Claude).** В Windows PowerShell:

```powershell
claude mcp add --scope user --transport stdio whisper-agent -- node "$env:LOCALAPPDATA\WhisperAgent\src\mcp.mjs"
claude mcp get whisper-agent
```

Для длинных файлов можно установить `MCP_TOOL_TIMEOUT` в окружении Claude или `timeout` в записи сервера. [Документация Claude Code MCP](https://code.claude.com/docs/en/mcp). Конфигурация обычного чата Claude Desktop (`claude_desktop_config.json`) отделена от Claude Code.

**Claude Cowork.** Для локального сеанса Cowork в приложении Claude Desktop подготовлен минимальный плагин [`integrations/claude-plugin`](integrations/claude-plugin). Установщик копирует его в `%LOCALAPPDATA%\WhisperAgent\claude-plugin`; загрузите эту папку через **Customize → Plugins → Add → Upload plugin**. Плагин содержит только локальный MCP и ссылается на `%LOCALAPPDATA%\WhisperAgent`; общий скил вы создаёте отдельно. Локальный MCP работает в Cowork-сеансах, исполняемых на вашем компьютере через Desktop. В облачном сеансе Cowork он не запускается; доступность зависит от типа сеанса и настроек вашей организации. Проверяйте инструмент в новом локальном сеансе Desktop. [Поддержка плагинов по поверхностям Claude](https://claude.com/docs/plugins/build), [архитектура Cowork](https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview).

**OpenCode.** После `connect-windows.ps1` проверьте `opencode mcp list`. Если скрипт пропустил OpenCode или у вас уже есть `opencode.jsonc`, добавьте запись вручную в глобальный `%USERPROFILE%\.config\opencode\opencode.json` либо в существующий `opencode.jsonc`, сохранив остальные поля.

Для **OpenCode 2.x** сервер находится в `mcp.servers`, а лимит выполнения — в `timeout.execution`:

```json
{
  "mcp": {
    "servers": {
      "whisper-agent": {
        "type": "local",
        "command": ["node", "C:\\Users\\SAWA\\AppData\\Local\\WhisperAgent\\src\\mcp.mjs"],
        "timeout": { "execution": 3600000 }
      }
    }
  }
}
```

Для **OpenCode 1.x** запись находится непосредственно в `mcp`:

```json
{
  "mcp": {
    "whisper-agent": {
      "type": "local",
      "command": ["node", "C:\\Users\\SAWA\\AppData\\Local\\WhisperAgent\\src\\mcp.mjs"],
      "enabled": true,
      "timeout": 3600000
    }
  }
}
```

Замените путь на фактическое значение `$env:LOCALAPPDATA`. После сохранения проверьте `opencode mcp list`. [Документация OpenCode 2.x](https://opencode.ai/v2/docs/mcp-servers), [OpenCode 1.x](https://opencode.ai/docs/en/mcp-servers).

## Обновление

После обновления файлов репозитория повторите `install-windows.ps1` из раздела первого запуска и перезапустите приложения агентов. Путь к MCP остаётся прежним, поэтому повторно подключать уже настроенный сервер обычно не требуется. Установщик снова выполняет `docker build`: если обновился базовый образ, загрузка CUDA-зависимостей может занять много времени. Том с моделями и журнал сохраняются.

## Из WSL

Сначала запустите Docker Desktop в Windows. Затем в обычном терминале WSL, где `docker version` видит Docker Desktop, из каталога репозитория выполните:

```bash
npm ci
docker build -t whisper-agent:torch2.13-cu132 .
node src/cli.mjs check
node src/cli.mjs list --project /home/sawa/projects/example
node src/cli.mjs transcribe --project /home/sawa/projects/example --output /home/sawa/projects/example/transcripts --format txt
```

Для WSL-версии агента укажите абсолютный Linux-путь к `src/mcp.mjs` в его локальной MCP-конфигурации. Windows-приложения должны использовать установленный Windows-путь из раздела выше; пути Windows и WSL в одном MCP-процессе не смешиваются. Журнал WSL по умолчанию: `$XDG_STATE_HOME/whisper-agent/runs.jsonl` либо `~/.local/state/whisper-agent/runs.jsonl`.

## Контракт для общего скила

1. По запросу «распознай файлы в папке проекта» определите абсолютный корень текущего проекта и вызовите `list_media`.
2. Прочитайте правила проекта и запрос пользователя о том, **куда** и **в каком формате** сохранять. Если хотя бы одного правила нет, спросите пользователя до вызова `transcribe_project`. Не выбирайте молча каталог или формат.
3. Вызовите `transcribe_project(project_dir, output_dir, output_format)`; MCP всегда использует `small`, начальный язык — `ru`. `overwrite` используйте лишь при явном разрешении.
4. Сообщите пользователю статус, имена обработанных файлов, пути результатов, время и ошибки. Полный текст остаётся в файлах результатов.

Для проверки после первого запуска: откройте один `transcript.txt`, одну строку `runs.jsonl`, убедитесь, что в журнале нет текста, и проверьте `docker ps -a` — рабочий контейнер должен быть удалён. При ошибке `CUDA GPU is unavailable` проверьте Docker Desktop WSL 2 GPU, затем `node ...\cli.mjs check`. Не включайте CPU fallback: это скрывает проблемы с GPU.

## Эксперименты и ограничения

Собирайте альтернативы под отдельными тегами, например `docker build -t whisper-agent:experiment-cu132 .`, затем выбирайте их через `--image` в CLI или `image_tag` в MCP. Другую модель пользователь выбирает только при ручном запуске CLI с `--model`; кэш весов общий. Менять `Dockerfile` и пересобирать рабочий тег можно, но для воспроизводимого сравнения храните разные теги. Восемь гигабайт VRAM подходят для первого опыта с `small`; более крупная модель может не поместиться. На шуме и тишине Whisper может ошибаться, поэтому текст требует проверки.

Командная песочница агента может не иметь доступа к Docker daemon (`EPERM`) и GPU. Проверяйте Docker, GPU и Windows-приложения в обычной Windows/WSL-сессии по командам выше. Не требуется менять права Docker socket или отключать песочницу.
