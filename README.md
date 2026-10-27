# Локальный Whisper для проектов

Распознаёт аудио и видео в текущем проекте через одноразовый Docker-контейнер на NVIDIA GPU. Начальные параметры: официальная многоязычная модель `small`, язык `ru`, задача `transcribe`. Контейнер удаляется после каждой команды (`docker run --rm`); модель хранится в томе `whisper-agent-models`, поэтому повторная загрузка не нужна. Полный текст попадает только в файлы результатов. Журнал JSONL содержит файлы, время, длительность, статус и ошибки.

## Требования

- Windows 11/10, Docker Desktop с WSL 2 и включённым GPU, Node.js 20+; для WSL нужны Node.js 20+ и доступ к Docker Desktop из обычного терминала.
- RTX 5060 Laptop GPU уже прошла проверку NVIDIA `nbody` с `docker run --rm --gpus all` в PowerShell пользователя. Эта проверка подтверждает проброс GPU, но не работу конкретного PyTorch-образа.
- Достаточно места для крупного образа PyTorch/CUDA и модели `small`. Первый запуск скачает веса в Docker volume; без сети это не сработает.

Образ использует `openai-whisper==20250625`, `torch==2.13.0` из официального индекса `cu132` и `ffmpeg`. [Исходный Whisper](https://github.com/openai/whisper), [документация Docker Desktop GPU](https://docs.docker.com/desktop/features/gpu/).

## Установка на Windows

В обычном PowerShell, где доступен Docker Desktop, из каталога этого репозитория:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
```

Установщик копирует runtime в `%LOCALAPPDATA%\WhisperAgent`, выполняет `npm ci`, собирает образ `whisper-agent:torch2.13-cu132` и проверяет `torch.cuda.is_available()` внутри контейнера. Он не меняет настройки агентов, журналы и Docker volume. При обновлении повторите команду. Если репозиторий находится в WSL, запускайте PowerShell из Windows по пути `\\wsl.localhost\<имя-дистрибутива>\home\sawa\projects\whisper` либо скопируйте репозиторий на Windows-диск.

Ручная проверка:

```powershell
$Agent = Join-Path $env:LOCALAPPDATA 'WhisperAgent\src\cli.mjs'
node $Agent check
node $Agent list --project 'C:\Users\SAWA\Мой проект'
node $Agent transcribe --project 'C:\Users\SAWA\Мой проект' --output 'C:\Users\SAWA\Мой проект\transcripts' --format txt
```

Последняя команда создаёт `transcripts\<относительный путь входного файла с расширением>\transcript.txt`. Например, `audio\call.mp3` и `audio\call.wav` попадают в разные каталоги. Если результатов нет или файл уже существует, команда возвращает ошибку; `--overwrite` разрешает замену. Поддерживаются `txt`, `srt`, `vtt`, `tsv`, `json`, `all`. Формат `json` содержит текст в файле результата; журнал никогда не содержит его. `all` сохраняет все пять форматов.

Поиск рекурсивный: `wav`, `mp3`, `m4a`, `flac`, `ogg`, `opus`, `aac`, `wma`, `mp4`, `mov`, `mkv`, `webm`, `avi`. Пропускаются символические ссылки, `.git`, `node_modules`, `.venv`, `dist`, `build` и каталог результатов, если он находится внутри проекта. Проект монтируется в контейнер только для чтения; результат — отдельно для записи.

Журнал Windows: `%LOCALAPPDATA%\WhisperAgent\runs.jsonl`; переменная `WHISPER_LOG_PATH` переопределяет путь. Каждая строка — JSON одной попытки распознавания: входные файлы, выходные пути, длительности в миллисекундах, ошибки, модель, язык, образ. При сбое запуска Docker сохраняется запись с общей ошибкой и пустым списком файлов.

## Подключение агентов Windows

После установки выполните **одну команду** в Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\WhisperAgent\connect-windows.ps1"
```

Скрипт регистрирует локальный MCP в установленных Codex, Claude Code и OpenCode с часовым лимитом на распознавание. Уже существующую запись `whisper-agent` он не меняет. Если OpenCode хранит конфигурацию в JSONC или CLI приложения отсутствует, скрипт сообщает, что нужно подключить вручную. После подключения перезапустите Windows-приложения. **Отдельно запускать MCP не нужно:** агент запускает процесс при подключении и обращается к нему по запросу. Docker-контейнер создаётся только для команды распознавания или проверки GPU и удаляется после неё.

Чтобы запустить MCP вручную для диагностики, выполните `node "$env:LOCALAPPDATA\WhisperAgent\src\mcp.mjs"`. Процесс будет ожидать запросы MCP по stdin; отсутствие обычного вывода — ожидаемо. Ниже приведены ручные способы подключения, если автоматический скрипт пропустил приложение.

MCP-сервер запускается локально командой `node "%LOCALAPPDATA%\WhisperAgent\src\mcp.mjs"` (в конфигурации указывайте **развёрнутый абсолютный путь**, а не `%LOCALAPPDATA%`). Он предоставляет `list_media` и `transcribe_project`. Подключение не требует выдавать агентской командной песочнице доступ к Docker socket: Docker вызывает установленный локальный MCP-процесс.

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

**OpenCode.** Добавьте в глобальный `%USERPROFILE%\.config\opencode\opencode.json` или существующий `opencode.jsonc` запись, сохранив другие поля:

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

Замените путь на фактическое значение `$env:LOCALAPPDATA`. Проверьте `opencode mcp list`. [Документация OpenCode MCP](https://docs.opencode.ai/docs/mcp-servers/).

## Из WSL

В обычном терминале WSL, где `docker version` видит Docker Desktop:

```bash
npm ci
docker build -t whisper-agent:torch2.13-cu132 .
node src/cli.mjs check
node src/cli.mjs list --project /home/sawa/projects/example
node src/cli.mjs transcribe --project /home/sawa/projects/example --output /home/sawa/projects/example/transcripts --format txt
```

Для WSL-версии агента укажите абсолютный Linux-путь к `src/mcp.mjs` в его локальной MCP-конфигурации. Журнал по умолчанию: `$XDG_STATE_HOME/whisper-agent/runs.jsonl` либо `~/.local/state/whisper-agent/runs.jsonl`.

## Контракт для общего скила

1. По запросу «распознай файлы в папке проекта» определите абсолютный корень текущего проекта и вызовите `list_media`.
2. Прочитайте правила проекта и запрос пользователя о том, **куда** и **в каком формате** сохранять. Если хотя бы одного правила нет, спросите пользователя до вызова `transcribe_project`. Не выбирайте молча каталог или формат.
3. Вызовите `transcribe_project(project_dir, output_dir, output_format)`; начальные параметры `small` и `ru`. `overwrite` используйте лишь при явном разрешении.
4. Сообщите пользователю статус, имена обработанных файлов, пути результатов, время и ошибки. Полный текст остаётся в файлах результатов.

Для проверки после первого запуска: откройте один `transcript.txt`, одну строку `runs.jsonl`, убедитесь, что в журнале нет текста, и проверьте `docker ps -a` — рабочий контейнер должен быть удалён. При ошибке `CUDA GPU is unavailable` проверьте Docker Desktop WSL 2 GPU, затем `node ...\cli.mjs check`. Не включайте CPU fallback: это скрывает проблемы с GPU.

## Эксперименты и ограничения

Собирайте альтернативы под отдельными тегами, например `docker build -t whisper-agent:experiment-cu132 .`, затем выбирайте их через `--image` в CLI или `image_tag` в MCP. Модель выбирается через `--model` или `model`; кэш весов общий. Менять `Dockerfile` и пересобирать рабочий тег можно, но для воспроизводимого сравнения храните разные теги. Восемь гигабайт VRAM подходят для первого опыта с `small`; более крупная модель может не поместиться. На шуме и тишине Whisper может ошибаться, поэтому текст требует проверки.

Текущая песочница Codex этого репозитория не имеет доступа к Docker daemon (`EPERM`) и `/dev/dxg`; поэтому сборка, PyTorch GPU check, Windows-установщик, реальная русская запись и подключение Windows-приложений должны быть проверены в обычной Windows/WSL-сессии по командам выше. Не требуется менять права Docker socket или отключать песочницу.
