"""Readable diarized turns and unchanged ordinary Whisper subtitles."""

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from container import worker


class DiarizedOutputTests(unittest.TestCase):
    def test_merges_adjacent_same_speaker_across_whisper_segments(self):
        document = {"segments": [
            {"start": 123.9, "end": 126, "speaker_id": "Speaker1", "text": " Закрою вкладки."},
            {"start": 126, "end": 129, "speaker_id": "Speaker1", "text": " Сейчас зависнет ноутбук."},
            {"start": 130, "end": 132, "speaker_id": "Speaker2", "text": " Это тоже можно закрыть."},
            {"start": 152, "end": 155, "speaker_id": "Speaker1", "text": " Я понял."},
            {"start": 194, "end": 195, "speaker_id": "Speaker1", "text": " Сейчас\nвключу экран."},
            {"start": 196, "end": 198, "speaker_id": None, "text": " Неясный голос."},
            {"start": 199, "end": 200, "speaker_id": None, "text": " Другой фрагмент."},
            {"start": 3723.8, "end": 3725, "speaker_id": "Speaker1", "text": " Продолжим."},
        ]}
        before = copy.deepcopy(document)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            worker.write_diarized(document, root)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["transcript.txt"])
            self.assertEqual((root / "transcript.txt").read_text(),
                "[2:03] Speaker1: Закрою вкладки. Сейчас зависнет ноутбук.\n\n"
                "[2:10] Speaker2: Это тоже можно закрыть.\n\n"
                "[2:32] Speaker1: Я понял. Сейчас включу экран.\n\n"
                "[3:16] SpeakerUnknown: Неясный голос.\n\n"
                "[3:19] SpeakerUnknown: Другой фрагмент.\n\n"
                "[1:02:03] Speaker1: Продолжим.\n")
        self.assertEqual(document, before)

    def test_silence_creates_empty_txt_without_invented_speaker(self):
        with tempfile.TemporaryDirectory() as temp:
            worker.write_diarized({"segments": []}, Path(temp))
            self.assertEqual((Path(temp) / "transcript.txt").read_text(), "")

    @unittest.skipUnless(importlib.util.find_spec("whisper"), "Run in the Whisper image for the real SRT writer")
    def test_without_diarization_preserves_original_whisper_srt(self):
        import whisper
        import torch
        with tempfile.TemporaryDirectory() as temp:
            root, out = Path(temp) / "project", Path(temp) / "out"
            root.mkdir()
            (root / "one.wav").write_bytes(b"synthetic")
            original = {"language": "ru", "text": "Привет. Да.", "segments": [
                {"start": 0, "end": 1, "text": " Привет."},
                {"start": 1, "end": 2, "text": " Да."},
            ]}
            with patch.object(torch.cuda, "is_available", return_value=True), patch.object(whisper, "load_model") as load, patch.object(worker, "create_diarizer") as diarizer:
                load.return_value.transcribe.return_value = original
                summary = worker.transcribe_media(root, out, "srt")
                diarizer.assert_not_called()
                self.assertNotIn("word_timestamps", load.return_value.transcribe.call_args.kwargs)
            self.assertEqual(summary["status"], "success")
            self.assertEqual((out / "one.wav" / "transcript.srt").read_text(),
                "1\n00:00:00,000 --> 00:00:01,000\nПривет.\n\n"
                "2\n00:00:01,000 --> 00:00:02,000\nДа.\n\n")
