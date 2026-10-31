"""Discover media and plan output paths for the container worker."""

from __future__ import annotations

import os
import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

if __package__:
    from .diarization import build_document, create_diarizer
else:
    from diarization import build_document, create_diarizer


MEDIA_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac",
    ".wma", ".mp4", ".mov", ".mkv", ".webm", ".avi",
}
SKIP_DIRECTORIES = {".git", "node_modules", ".venv", "dist", "build"}
OUTPUT_FORMATS = ("txt", "vtt", "srt", "tsv", "json")


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


def planned_outputs(media: Path, project: Path, output: Path, format: str, diarize: bool = False) -> list[Path]:
    if format not in (*OUTPUT_FORMATS, "all"):
        raise ValueError(f"Unsupported output format: {format}")
    if diarize and format != "txt":
        raise ValueError("diarization requires txt output; use --format txt or disable --diarize")
    if media.is_symlink():
        raise ValueError("Symlink inputs are not supported")
    try:
        relative = media.resolve().relative_to(project.resolve())
    except ValueError as error:
        raise ValueError("Input is outside the project") from error
    formats = OUTPUT_FORMATS if format == "all" else (format,)
    targets = [output / relative / f"transcript.{extension}" for extension in formats]
    return targets


def preflight(
    project: Path,
    output: Path | None,
    format: str,
    overwrite: bool,
    excluded_relative: Path | None,
    diarize: bool = False,
) -> list[Path]:
    if output is None or not str(output).strip():
        raise ValueError("Output directory is required")
    if format not in (*OUTPUT_FORMATS, "all"):
        raise ValueError("Output format is required and must be supported")
    media = discover_media(project, excluded_relative)
    if not media:
        raise ValueError("No media files found in project")
    for item in media:
        for target in planned_outputs(item, project, output, format, diarize):
            _reject_output_symlinks(target, output)
            if not overwrite and target.exists():
                raise FileExistsError(f"Result already exists: {target}")
    return media


def _reject_output_symlinks(target: Path, output: Path) -> None:
    current = target
    while current != output:
        if current.is_symlink():
            raise ValueError(f"Result path contains a symlink: {current}")
        current = current.parent


def write_diarized(document: dict, output: Path) -> None:
    """Write one timestamped paragraph per consecutive identified speaker."""
    blocks = []
    for segment in document["segments"]:
        speaker = segment["speaker_id"]
        text = " ".join(segment["text"].split())
        if blocks and speaker is not None and blocks[-1]["speaker_id"] == speaker:
            blocks[-1]["parts"].append(text)
        else:
            blocks.append({"start": segment["start"], "speaker_id": speaker, "parts": [text]})
    paragraphs = []
    for block in blocks:
        seconds = int(block["start"])
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        timestamp = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
        text = " ".join(part for part in block["parts"] if part)
        paragraphs.append(f"[{timestamp}] {block['speaker_id'] or 'SpeakerUnknown'}: {text}")
    (output / "transcript.txt").write_text("\n\n".join(paragraphs) + ("\n" if paragraphs else ""), encoding="utf-8")


def transcribe_media(
    project: Path,
    output: Path,
    format: str,
    model_name: str = "small",
    language: str = "ru",
    overwrite: bool = False,
    excluded_relative: Path | None = None,
    diarize: bool = False,
) -> dict:
    if model_name.endswith(".en") and language != "en":
        raise ValueError("English-only model cannot transcribe Russian")
    media = preflight(project, output, format, overwrite, excluded_relative, diarize)

    import torch
    import whisper

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is unavailable; refusing CPU fallback")
    model = whisper.load_model(model_name, device="cuda", download_root="/models")
    diarizer = create_diarizer() if diarize else None
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    files = []
    for item in media:
        item_started = time.perf_counter()
        relative = item.relative_to(project.resolve())
        outputs = planned_outputs(item, project, output, format, diarize)
        entry = {"input": relative.as_posix(), "outputs": [], "duration_ms": 0, "error": None}
        try:
            target_dir = output / relative
            options = {"language": language, "task": "transcribe", "verbose": None}
            if diarize:
                options["word_timestamps"] = True
            result = model.transcribe(str(item), **options)
            document = None
            if diarizer is not None:
                try:
                    turns, exclusive_turns = diarizer.analyze(item)
                    document = build_document(result, turns, exclusive_turns, relative.as_posix())
                except Exception:
                    raise RuntimeError("Diarization failed; check audio and GPU resources") from None
            with tempfile.TemporaryDirectory(prefix=".whisper-", dir=output) as staging:
                if document is not None:
                    write_diarized(document, Path(staging))
                else:
                    whisper.utils.get_writer(format, staging)(result, "transcript.media")
                staged = [Path(staging) / target.name for target in outputs]
                missing = [path.name for path in staged if not path.is_file()]
                if missing:
                    raise RuntimeError(f"Writer did not create expected outputs: {', '.join(missing)}")
                _reject_output_symlinks(outputs[0], output)
                target_dir.mkdir(parents=True, exist_ok=True)
                for source, target in zip(staged, outputs):
                    _reject_output_symlinks(target, output)
                    if target.exists() and not overwrite:
                        raise FileExistsError(f"Result already exists: {target}")
                    os.replace(source, target)
                    entry["outputs"].append(target.relative_to(output).as_posix())
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
        "diarize": diarize,
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
    transcribe_parser.add_argument("--diarize", action="store_true")
    args = parser.parse_args(argv)
    try:
        excluded = _relative_exclusion(args.exclude_relative)
        if args.command == "list":
            result = {"files": [path.relative_to(args.project.resolve()).as_posix() for path in discover_media(args.project, excluded)]}
        else:
            result = transcribe_media(args.project, args.output, args.format, args.model, args.language, args.overwrite, excluded, args.diarize)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("status", "success") == "success" else 1
    except Exception as error:
        print(json.dumps({"status": "error", "files": [], "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
