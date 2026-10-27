"""Discover media and plan output paths for the container worker."""

from __future__ import annotations

import os
import argparse
import json
import sys
import time
from pathlib import Path


MEDIA_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac",
    ".wma", ".mp4", ".mov", ".mkv", ".webm", ".avi",
}
SKIP_DIRECTORIES = {".git", "node_modules", ".venv", "dist", "build"}
OUTPUT_FORMATS = ("txt", "vtt", "srt", "tsv", "json", "jsonl")


def discover_media(project: Path, excluded_relative: Path | None) -> list[Path]:
    project = project.resolve()
    if not project.is_dir():
        raise ValueError(f"Project directory does not exist: {project}")
    excluded = excluded_relative.parts if excluded_relative is not None else ()
    found: list[Path] = []
    for directory, names, files in os.walk(project, followlinks=False):
        current = Path(directory)
        names[:] = [
            name for name in names
            if name not in SKIP_DIRECTORIES
            and not (current / name).is_symlink()
            and not (excluded and (current / name).relative_to(project).parts[: len(excluded)] == excluded)
        ]
        for name in files:
            media = current / name
            if media.is_symlink() or media.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            if excluded and media.relative_to(project).parts[: len(excluded)] == excluded:
                continue
            found.append(media)
    return sorted(found, key=lambda path: path.relative_to(project).as_posix().casefold())


def planned_outputs(media: Path, project: Path, output: Path, format: str) -> list[Path]:
    if format not in (*OUTPUT_FORMATS, "all"):
        raise ValueError(f"Unsupported output format: {format}")
    if media.is_symlink():
        raise ValueError("Symlink inputs are not supported")
    try:
        relative = media.resolve().relative_to(project.resolve())
    except ValueError as error:
        raise ValueError("Input is outside the project") from error
    formats = OUTPUT_FORMATS if format == "all" else (format,)
    return [output / relative / f"transcript.{extension}" for extension in formats]


def preflight(
    project: Path,
    output: Path | None,
    format: str,
    overwrite: bool,
    excluded_relative: Path | None,
) -> list[Path]:
    if output is None or not str(output).strip():
        raise ValueError("Output directory is required")
    if format not in (*OUTPUT_FORMATS, "all"):
        raise ValueError("Output format is required and must be supported")
    media = discover_media(project, excluded_relative)
    if not media:
        raise ValueError("No media files found in project")
    if not overwrite:
        for item in media:
            for target in planned_outputs(item, project, output, format):
                if target.exists():
                    raise FileExistsError(f"Result already exists: {target}")
    return media


def transcribe_media(
    project: Path,
    output: Path,
    format: str,
    model_name: str = "small",
    language: str = "ru",
    overwrite: bool = False,
    excluded_relative: Path | None = None,
) -> dict:
    if model_name.endswith(".en") and language != "en":
        raise ValueError("English-only model cannot transcribe Russian")
    media = preflight(project, output, format, overwrite, excluded_relative)

    import torch
    import whisper

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is unavailable; refusing CPU fallback")
    model = whisper.load_model(model_name, device="cuda", download_root="/models")
    started = time.perf_counter()
    files = []
    for item in media:
        item_started = time.perf_counter()
        relative = item.relative_to(project.resolve())
        outputs = planned_outputs(item, project, output, format)
        entry = {"input": relative.as_posix(), "outputs": [], "duration_ms": 0, "error": None}
        try:
            target_dir = output / relative
            target_dir.mkdir(parents=True, exist_ok=True)
            result = model.transcribe(str(item), language=language, task="transcribe", verbose=None)
            writer = whisper.utils.get_writer(format, str(target_dir))
            writer(result, "transcript.media")
            entry["outputs"] = [path.relative_to(output).as_posix() for path in outputs]
        except Exception as error:
            entry["error"] = str(error)
            print(f"Failed to transcribe {relative}: {error}", file=sys.stderr)
        finally:
            entry["duration_ms"] = round((time.perf_counter() - item_started) * 1000)
            files.append(entry)
    successes = sum(item["error"] is None for item in files)
    status = "success" if successes == len(files) else "partial" if successes else "error"
    return {
        "status": status,
        "files": files,
        "total_duration_ms": round((time.perf_counter() - started) * 1000),
        "model": model_name,
        "language": language,
    }


def _relative_exclusion(value: str | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path == Path("."):
        raise ValueError("Exclude path must be relative to project")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local GPU Whisper worker")
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--project", type=Path, required=True)
    list_parser.add_argument("--exclude-relative")
    transcribe_parser = subparsers.add_parser("transcribe")
    transcribe_parser.add_argument("--project", type=Path, required=True)
    transcribe_parser.add_argument("--output", type=Path, required=True)
    transcribe_parser.add_argument("--format", required=True)
    transcribe_parser.add_argument("--model", default="small")
    transcribe_parser.add_argument("--language", default="ru")
    transcribe_parser.add_argument("--exclude-relative")
    transcribe_parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        excluded = _relative_exclusion(args.exclude_relative)
        if args.command == "list":
            result = {"files": [path.relative_to(args.project.resolve()).as_posix() for path in discover_media(args.project, excluded)]}
        else:
            result = transcribe_media(args.project, args.output, args.format, args.model, args.language, args.overwrite, excluded)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("status", "success") == "success" else 1
    except Exception as error:
        print(json.dumps({"status": "error", "files": [], "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
