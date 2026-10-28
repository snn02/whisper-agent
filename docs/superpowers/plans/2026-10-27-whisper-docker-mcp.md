# Whisper Docker + MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Распознавать русскую речь из медиафайлов любого текущего проекта на RTX 5060 через одноразовый Docker-контейнер, доступный Codex, Claude Code/Cowork и OpenCode через локальный MCP.

**Architecture:** Образ содержит официальный Whisper и Python-обработчик. Хостовый Node-процесс предоставляет CLI и два MCP-инструмента, вызывает `docker run --rm` без shell и пишет журнал метаданных. Входной проект монтируется только для чтения, результаты — отдельно для записи, модели — в общем именованном томе.

**Tech Stack:** Python 3.12, `openai-whisper==20250625`, `torch==2.13.0` из `cu132`, `ffmpeg`, Docker Desktop с WSL 2, Node.js 20+, `@modelcontextprotocol/sdk@1.32.2`, `zod@4.6.7`.

**Spec:** `docs/superpowers/specs/2026-10-27-whisper-docker-design.md`

**Состояние 2026-10-27:** статические задачи 1–5 реализованы и зафиксированы на `main`; сборка Docker, проверка GPU на рабочем образе, PowerShell-установщик и запуск в Windows-приложениях остаются непроверенными из этой песочницы. Чекбоксы ниже сохранены как исходный план, а не текущий статус.

**Изменение 2026-10-28:** после запуска `medium` MCP закреплён за моделью `small`; другая модель доступна только при ручном запуске CLI. Исторический интерфейс Task 4 ниже описывает исходный план.

## Global Constraints

- Рабочий профиль: многоязычная модель `small`, `language=ru`, `task=transcribe`, `device=cuda`; CPU fallback запрещён.
- Контейнер запускается на запрос и удаляется после него; тест `nbody` на Windows уже подтвердил доступ Docker к RTX 5060 Laptop GPU, compute capability 12.0.
- Формат и каталог результата обязательны; агент спрашивает недостающие значения у пользователя, если их не определяют запрос или правила проекта. Инструмент возвращает ошибку при пустых значениях.
- Полный текст остаётся только в выходных файлах; журнал содержит файлы, длительность, ошибки и служебные метаданные.
- Общий скил пользователь создаёт сам. Проект поставляет MCP-инструменты, CLI и контракт для этого скила; не меняет глобальные конфиги агентов автоматически.
- Репозиторий инициализирован в `/home/sawa/projects/whisper`, ветка `main`; первый коммит `f9f0514` создан после Task 1.

## File Map

- `Dockerfile`: воспроизводимый образ с `ffmpeg`, CUDA-сборкой PyTorch и официальным Whisper.
- `container/worker.py`: поиск медиа, проверка путей и коллизий, распознавание, вывод JSON-сводки без текста.
- `tests/test_worker.py`: проверки поиска, путей результатов, ошибок и вызова Whisper с тестовым двойником без GPU.
- `package.json`, `package-lock.json`: закреплённые зависимости MCP и Node-команды.
- `src/core.mjs`: валидация хостовых путей, построение аргументов Docker, разбор сводки, журнал JSONL.
- `src/cli.mjs`: ручные команды `list`, `transcribe`, `check`.
- `src/mcp.mjs`: MCP-инструменты `list_media` и `transcribe_project` поверх `src/core.mjs`.
- `tests/core.test.mjs`, `tests/mcp.test.mjs`: проверки хостового слоя и MCP без настоящего Docker.
- `scripts/install-windows.ps1`: копирование runtime в `%LOCALAPPDATA%\WhisperAgent`, `npm ci`, сборка образа и печать команд подключения; не меняет чужие конфиги.
- `README.md`: установка Windows/WSL, ручной запуск, подключение трёх агентов, требования к скилу, проверки GPU и варианты образов.
- `.dockerignore`, `.gitignore`: исключить модели, результаты, журналы, `node_modules` и локальные тестовые данные.

## Review Focus

1. Два медиа с одинаковым stem (`call.mp3`, `call.wav`) должны получить разные каталоги результатов — Task 1.
2. Символическая ссылка за пределы проекта не должна попасть в список файлов — Task 1.
3. Windows-путь с пробелами и Unicode должен передаваться Docker единым аргументом — Task 3.
4. Ошибка одного файла должна оставить результаты остальных и попасть в журнал без текста — Tasks 2 и 3.
5. Повторный запуск не должен молча перезаписать существующий результат — Task 1.

---

### Task 1: Поиск медиа и безопасные пути результатов

**Files:** Create `container/worker.py`, `tests/test_worker.py`.

**Interfaces:** Produces `discover_media(project: Path, excluded_relative: Path | None) -> list[Path]`, `planned_outputs(media: Path, project: Path, output: Path, format: str) -> list[Path]`, `preflight(project: Path, output: Path, format: str, overwrite: bool, excluded_relative: Path | None) -> list[Path]` for Task 2. `excluded_relative` is the output directory's path relative to the project when output lives inside it. Relative output layout: `<output>/<relative media path including extension>/transcript.<format>`.

- [ ] Write `tests/test_worker.py` cases: recursive `.wav/.mp3/.m4a/.flac/.ogg/.opus/.aac/.wma/.mp4/.mov/.mkv/.webm/.avi` discovery; skip `.git`, `node_modules`, `.venv`, `dist`, `build`, all symlinks, and output subtree; `call.mp3` versus `call.wav`; no files; missing format/output; existing target without `overwrite`.
- [ ] Run `python3 -m unittest discover -s tests -p 'test_worker.py' -v`; expect failures for missing functions.
- [ ] Implement the three interfaces in `container/worker.py`, using `Path.relative_to` to keep inputs in the project and exactly `txt|srt|vtt|tsv|json|all` formats. For `all`, plan five output files (the pinned `openai-whisper==20250625` writer does not support `jsonl`).
- [ ] Run `python3 -m unittest discover -s tests -p 'test_worker.py' -v`; expect all Task 1 cases to pass.
- [ ] Commit these files if git is available; otherwise record the no-git condition in the handoff.

### Task 2: GPU-обработчик и образ

**Files:** Modify `container/worker.py`, `tests/test_worker.py`; create `Dockerfile`, `.dockerignore`.

**Interfaces:** Consumes Task 1 functions. Produces CLI `python /app/worker.py list --project /input [--exclude-relative <path>]` returning `{files:[relative paths]}` and `python /app/worker.py transcribe --project /input --output /output --format <format> [--exclude-relative <path>] [--model small] [--language ru] [--overwrite]`; transcribe stdout ends with one JSON object `{status, files:[{input, outputs, duration_ms, error}], total_duration_ms, model, language}` and never includes transcription text. Exit code 0 only if every file succeeds.

- [ ] Add tests with a fake `whisper.load_model`/writer: model loads once; `device='cuda'`, `language='ru'`, `verbose=None`; per-file duration/status; one failed file does not stop others; summary excludes full text; no CPU fallback; reject `.en` models with Russian.
- [ ] Run `python3 -m unittest discover -s tests -p 'test_worker.py' -v`; expect the new cases to fail.
- [ ] Implement `list`/`transcribe` CLI and writer calls. Use `whisper.utils.get_writer` with a synthetic basename `transcript.media` inside each media-specific output directory; check targets before model loading. Print diagnostics to stderr and only JSON summary to stdout.
- [ ] Add `Dockerfile` based on Python 3.12 slim, install `ffmpeg`, `torch==2.13.0` from `https://download.pytorch.org/whl/cu132`, then `openai-whisper==20250625`; set model cache to `/models`. Image tag: `whisper-agent:torch2.13-cu132`.
- [ ] Run `python3 -m unittest discover -s tests -p 'test_worker.py' -v`; expect all cases to pass. Run `docker build -t whisper-agent:torch2.13-cu132 .` and `docker run --rm --gpus all whisper-agent:torch2.13-cu132 python -c "import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"` in a normal Windows/WSL session; expect RTX 5060. The current Codex sandbox cannot perform the Docker commands.
- [ ] Commit if git is available.

### Task 3: Общий хостовый запуск и журнал

**Files:** Create `package.json`, `package-lock.json`, `src/core.mjs`, `src/cli.mjs`, `tests/core.test.mjs`, `.gitignore`.

**Interfaces:** Produces `listMedia({projectDir, imageTag}, deps) -> Promise<{files: string[]}>` and `transcribeProject({projectDir, outputDir, outputFormat, model='small', language='ru', imageTag='whisper-agent:torch2.13-cu132', overwrite=false}, deps) -> Promise<Summary>`. `deps` injects `spawn`, clock and filesystem for tests. CLI commands mirror these parameters; `check` runs a short `torch.cuda.is_available()` check. Journal path: `WHISPER_LOG_PATH`, else `%LOCALAPPDATA%\WhisperAgent\runs.jsonl` on Windows or `$XDG_STATE_HOME/whisper-agent/runs.jsonl` on Linux (fallback `~/.local/state`).

- [ ] Write Node tests for required absolute Windows/Linux project/output paths, required output format, rejection when output equals project root, Docker argv as discrete arguments for `C:\Users\SAWA\Проект с пробелом`, read-only input mount, writable output mount, named model volume, `--gpus all`, `--rm`, nonzero Docker exit, partial failure, JSONL log with durations/errors and no transcript text.
- [ ] Run `node --test tests/core.test.mjs`; expect failures for missing functions.
- [ ] Implement `src/core.mjs` with `spawn` and argument arrays, no shell; use `path.win32` for Windows absolute-path validation even in Linux tests; derive `--exclude-relative` for output below project; create output/log directories only after validation; preserve Docker exit/stderr in error records.
- [ ] Run `node --test tests/core.test.mjs`; expect all cases to pass.
- [ ] Implement `src/cli.mjs` and package scripts; install exact MCP dependencies with `npm install --save-exact @modelcontextprotocol/sdk@1.32.2 zod@4.6.7` to generate lockfile. Run `node src/cli.mjs --help`; expect documented commands.
- [ ] Commit if git is available.

### Task 4: MCP для Codex, Claude и OpenCode

**Files:** Create `src/mcp.mjs`, `tests/mcp.test.mjs`; modify `package.json`.

**Interfaces:** Consumes Task 3 `listMedia` and `transcribeProject`. MCP tools: `list_media(project_dir, image_tag?)` and `transcribe_project(project_dir, output_dir, output_format, model?, language?, image_tag?, overwrite?)`. `output_dir` and `output_format` are required. Tool descriptions instruct the agent to use project/user rules and ask for missing save choices before calling `transcribe_project`.

- [ ] Write in-memory MCP client tests for tool discovery, `list_media`, rejected missing save choices, `transcribe_project` parameter mapping, and error/partial-result reporting without transcript text.
- [ ] Run `node --test tests/mcp.test.mjs`; expect failures for missing server.
- [ ] Implement stdio server with `@modelcontextprotocol/sdk` and Zod schemas in `src/mcp.mjs`, exposing exactly the two tools; keep protocol output on stdout and diagnostics on stderr.
- [ ] Run `node --test tests/mcp.test.mjs`; expect all cases to pass. Run `npm test` for Node tests and `python3 -m unittest discover -s tests -p 'test_worker.py' -v` for Python tests.
- [ ] Commit if git is available.

### Task 5: Windows delivery, agent setup and end-to-end check

**Files:** Create `scripts/install-windows.ps1`, `README.md`; modify `.gitignore` if needed.

**Interfaces:** Consumes Task 2 image and Task 4 MCP command. Installer writes runtime only under `%LOCALAPPDATA%\WhisperAgent`, prints the absolute Windows `node ...\src\mcp.mjs` command for Codex/Claude/OpenCode, and does not rewrite their existing settings. README specifies Windows and WSL setup plus the common skill contract.

- [ ] Write PowerShell installer to copy only runtime/build files from this repo into `%LOCALAPPDATA%\WhisperAgent`; check Docker Desktop and Node 20+, run `npm ci`, build the image and run the GPU smoke check. Ensure repeat runs do not delete logs/model volume. Document the corresponding manual WSL commands.
- [ ] Document Codex Settings → MCP servers, Claude Code/Cowork local MCP, and OpenCode `mcp.local` using the same host command. Include a sample agent request and the mandatory ask-before-save rule for the user's skill.
- [ ] Verify static syntax (`npm test`, `python3 -m compileall container`, PowerShell parser on Windows), then run a short Russian recording supplied by the user through CLI and each available local agent surface. Inspect output files, JSONL log, and `docker ps -a` for container cleanup. Without a Russian sample, verify GPU with another short media file and mark Russian-content accuracy unverified. If this sandbox still blocks Docker/Windows app access, give the exact user-run commands and record those checks as pending rather than claiming completion.
- [ ] Commit if git is available; otherwise leave files ready for review in the workspace.

## Self-review notes

Tasks 1–5 cover scanning, no overwrite, Russian GPU inference, per-file logging, manual CLI, MCP and Windows delivery. Interfaces use the same option names at each boundary; the five Review Focus failures each have an owning test. Live Docker/Windows integration is a required acceptance check and is explicitly unavailable in this Codex sandbox until run through the installed local MCP or in the user's normal session.
