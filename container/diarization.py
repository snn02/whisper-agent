"""Local speaker intervals and a versioned transcript contract; no personal names."""

from __future__ import annotations

import math
import os
from collections import defaultdict
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


MODEL_ID = "pyannote/speaker-diarization-community-1"


def choose_speaker(start, end, turns):
    """Require a strict majority of the word's duration, without filling gaps."""
    if end <= start:
        return None
    overlap = defaultdict(float)
    for left, right, speaker in turns:
        overlap[speaker] += max(0, min(end, right) - max(start, left))
    ranked = sorted(overlap.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] <= (end - start) / 2:
        return None
    if len(ranked) > 1 and math.isclose(ranked[0][1], ranked[1][1]):
        return None
    return ranked[0][0]


def build_document(result, turns, exclusive_turns, source):
    turns = sorted(turns, key=lambda turn: (turn[0], turn[1], turn[2]))
    exclusive_turns = sorted(exclusive_turns, key=lambda turn: (turn[0], turn[1], turn[2]))
    labels = {}
    for _, _, speaker in sorted(turns + exclusive_turns):
        if speaker not in labels:
            labels[speaker] = f"Speaker{len(labels) + 1}"
    segments = []
    for original in result.get("segments", []):
        words = original.get("words", [])
        complete = bool(words) and all("start" in word and "end" in word and "word" in word for word in words)
        if not complete or "".join(word["word"] for word in words).strip() != original["text"].strip():
            segments.append({"start": original["start"], "end": original["end"], "text": original["text"], "speaker_id": None, "words": []})
            continue
        current = None
        for word in words:
            speaker_id = labels.get(choose_speaker(word["start"], word["end"], exclusive_turns))
            if current is None or current["speaker_id"] != speaker_id:
                current = {"start": word["start"], "end": word["end"], "text": "", "speaker_id": speaker_id, "words": []}
                segments.append(current)
            current["end"] = word["end"]
            current["text"] += word["word"]
            current["words"].append({"start": word["start"], "end": word["end"], "word": word["word"]})
    for index, segment in enumerate(segments, 1):
        segment["id"] = f"segment-{index}"
    return {
        "schema_version": 1,
        "source": source,
        "language": result.get("language"),
        "speakers": list(labels.values()),
        "turns": [{"start": start, "end": end, "speaker_id": labels[speaker]} for start, end, speaker in turns],
        "segments": segments,
    }


class LocalDiarizer:
    def __init__(self):
        # Third-party diagnostics must not leak tokens into the worker protocol.
        with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            import torch
            from pyannote.audio import Pipeline

            if not torch.cuda.is_available():
                raise RuntimeError("CUDA GPU is unavailable; refusing CPU fallback")
            self.pipeline = Pipeline.from_pretrained(
                MODEL_ID, token=os.environ.get("HF_TOKEN"), cache_dir="/models/huggingface/hub",
            )
            if self.pipeline is None:
                raise RuntimeError("Could not load diarization model")
            self.pipeline.to(torch.device("cuda"))

    def analyze(self, media: Path):
        with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            import torch
            import whisper

            # Use the same ffmpeg decoding as Whisper for every supported media format.
            waveform = torch.from_numpy(whisper.load_audio(str(media))).unsqueeze(0)
            output = self.pipeline({"waveform": waveform, "sample_rate": 16000})
            def intervals(annotation):
                return [(float(turn.start), float(turn.end), str(speaker)) for turn, _, speaker in annotation.itertracks(yield_label=True)]
            return intervals(output.speaker_diarization), intervals(output.exclusive_speaker_diarization)


def create_diarizer():
    try:
        return LocalDiarizer()
    except Exception:
        raise RuntimeError("Diarization initialization failed; check CUDA, model access, accepted Hugging Face conditions and HF_TOKEN") from None
