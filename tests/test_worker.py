import tempfile
import unittest
import json
import io
import sys
import types
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from container import worker


class MediaDiscoveryTests(unittest.TestCase):
    def test_finds_nested_media_and_skips_generated_folders_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "Записи").mkdir()
            (root / "Записи" / "встреча.mp3").write_bytes(b"audio")
            (root / "clip.MP4").write_bytes(b"video")
            (root / "notes.txt").write_text("text")
            for folder in (".git", "node_modules", ".venv", "dist", "build", "results"):
                (root / folder).mkdir()
                (root / folder / "hidden.wav").write_bytes(b"hidden")
            outside = root.parent / "outside.wav"
            (root / "linked.wav").symlink_to(outside)

            found = worker.discover_media(root, Path("results"))

            self.assertEqual([path.relative_to(root).as_posix() for path in found], ["clip.MP4", "Записи/встреча.mp3"])

    def test_empty_project_has_no_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(worker.discover_media(Path(temp), None), [])


class OutputPlanningTests(unittest.TestCase):
    def test_diarization_requires_txt_and_preflights_only_txt(self):
        with tempfile.TemporaryDirectory() as temp:
            root, out = Path(temp) / "project", Path(temp) / "out"
            root.mkdir()
            media = root / "call.wav"
            media.write_bytes(b"audio")
            target = out / "call.wav" / "transcript.txt"
            self.assertEqual(worker.planned_outputs(media, root, out, "txt", diarize=True), [target])
            for format in ("srt", "vtt", "tsv", "json", "all"):
                with self.subTest(format=format), self.assertRaisesRegex(ValueError, "diarization.*txt"):
                    worker.preflight(root, out, format, False, None, diarize=True)
            target.parent.mkdir(parents=True)
            target.write_text("old")
            with self.assertRaises(FileExistsError):
                worker.preflight(root, out, "txt", False, None, diarize=True)
            target.unlink()
            target.symlink_to(Path(temp) / "missing.txt")
            with self.assertRaisesRegex(ValueError, "symlink"):
                worker.preflight(root, out, "txt", True, None, diarize=True)

    def test_same_stem_different_extensions_have_distinct_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            out = Path(temp) / "results"
            root.mkdir()
            mp3 = root / "call.mp3"
            wav = root / "call.wav"
            mp3.write_bytes(b"a")
            wav.write_bytes(b"b")

            self.assertEqual(worker.planned_outputs(mp3, root, out, "txt"), [out / "call.mp3" / "transcript.txt"])
            self.assertEqual(worker.planned_outputs(wav, root, out, "txt"), [out / "call.wav" / "transcript.txt"])

    def test_all_format_plans_five_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            media = root / "audio.flac"
            media.write_bytes(b"audio")
            result = worker.planned_outputs(media, root, Path(temp) / "out", "all")
            self.assertEqual({path.suffix for path in result}, {".txt", ".srt", ".vtt", ".tsv", ".json"})

    def test_existing_result_requires_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            out = Path(temp) / "out"
            root.mkdir()
            (root / "sample.wav").write_bytes(b"audio")
            target = out / "sample.wav" / "transcript.txt"
            target.parent.mkdir(parents=True)
            target.write_text("old")

            with self.assertRaises(FileExistsError):
                worker.preflight(root, out, "txt", False, None)
            self.assertEqual(worker.preflight(root, out, "txt", True, None), [root / "sample.wav"])

    def test_dangling_result_symlink_and_parent_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            out = Path(temp) / "out"
            root.mkdir()
            (root / "sample.wav").write_bytes(b"audio")
            target = out / "sample.wav" / "transcript.txt"
            target.parent.mkdir(parents=True)
            target.symlink_to(Path(temp) / "missing.txt")
            with self.assertRaisesRegex(ValueError, "symlink"):
                worker.preflight(root, out, "txt", False, None)
            target.unlink()
            target.parent.rmdir()
            (out / "sample.wav").symlink_to(Path(temp) / "external", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                worker.preflight(root, out, "txt", True, None)

    def test_missing_save_choices_and_unsupported_format_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "sample.wav").write_bytes(b"audio")
            with self.assertRaises(ValueError):
                worker.preflight(root, None, "txt", False, None)
            with self.assertRaises(ValueError):
                worker.preflight(root, root / "out", "", False, None)
            with self.assertRaises(ValueError):
                worker.preflight(root, root / "out", "docx", False, None)
            with self.assertRaises(ValueError):
                worker.preflight(root, root / "out", "jsonl", False, None)


class TranscriptionTests(unittest.TestCase):
    def test_diarization_labels_selected_output_without_sidecar_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            root, out = Path(temp) / "project", Path(temp) / "out"
            root.mkdir()
            (root / "one.wav").write_bytes(b"one")
            diarizer = types.SimpleNamespace(analyze=lambda _: ([(0, 1, "voice")], [(0, 1, "voice")]))
            with patch.dict(sys.modules, self.fake_modules([])), patch.object(worker, "create_diarizer", return_value=diarizer):
                result = worker.transcribe_media(root, out, "txt", diarize=True)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["files"][0]["outputs"], ["one.wav/transcript.txt"])
            self.assertEqual((out / "one.wav" / "transcript.txt").read_text().strip(), "[0:00] Speaker1: секретный текст")
            self.assertEqual(sorted(p.name for p in (out / "one.wav").iterdir()), ["transcript.txt"])
            self.assertNotIn("секретный текст", json.dumps(result, ensure_ascii=False))

    def test_diarization_failure_keeps_other_files_and_does_not_publish_partial_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root, out = Path(temp) / "project", Path(temp) / "out"
            root.mkdir()
            for name in ("one.wav", "two.wav"):
                (root / name).write_bytes(b"audio")
            calls = []
            def analyze(file):
                if file.name == "one.wav":
                    raise RuntimeError("private transcript and hf_private_token")
                return [], []
            diarizer = types.SimpleNamespace(analyze=analyze)
            stderr = io.StringIO()
            with patch.dict(sys.modules, self.fake_modules(calls)), patch.object(worker, "create_diarizer", return_value=diarizer), redirect_stderr(stderr):
                result = worker.transcribe_media(root, out, "txt", diarize=True)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["files"][0]["outputs"], [])
            self.assertFalse((out / "one.wav" / "transcript.txt").exists())
            self.assertNotIn("private", json.dumps(result) + stderr.getvalue())

    def fake_modules(self, calls):
        class FakeModel:
            def transcribe(self, audio_path, **options):
                calls.append(("transcribe", Path(audio_path).name, options))
                if Path(audio_path).name == "bad.wav":
                    raise RuntimeError("decode failed")
                return {"text": "секретный текст", "segments": [{"text": "секретный текст", "start": 0, "end": 1, "words": [
                    {"word": "секретный", "start": 0, "end": 0.5}, {"word": " текст", "start": 0.5, "end": 1},
                ]}], "language": "ru"}

        def load_model(name, *, device, download_root):
            calls.append(("load", name, device, download_root))
            return FakeModel()

        def get_writer(format, output_dir):
            def write(result, audio_path):
                target = Path(output_dir) / f"{Path(audio_path).stem}.{format}"
                target.write_text(result["text"], encoding="utf-8")
            return write

        return {
            "torch": types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True)),
            "whisper": types.SimpleNamespace(load_model=load_model, utils=types.SimpleNamespace(get_writer=get_writer)),
        }

    def test_uses_cuda_ru_once_and_excludes_text_from_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            out = Path(temp) / "out"
            root.mkdir()
            (root / "one.wav").write_bytes(b"one")
            (root / "two.mp3").write_bytes(b"two")
            calls = []
            with patch.dict(sys.modules, self.fake_modules(calls)):
                summary = worker.transcribe_media(root, out, "txt", "small", "ru", False, None)

            self.assertEqual(summary["status"], "success")
            self.assertEqual([call for call in calls if call[0] == "load"], [("load", "small", "cuda", "/models")])
            self.assertEqual(len([call for call in calls if call[0] == "transcribe"]), 2)
            self.assertTrue(all(call[2]["language"] == "ru" and call[2]["verbose"] is None for call in calls if call[0] == "transcribe"))
            self.assertTrue((out / "one.wav" / "transcript.txt").exists())
            self.assertNotIn("секретный текст", json.dumps(summary, ensure_ascii=False))
            self.assertTrue(all(item["duration_ms"] >= 0 for item in summary["files"]))

    def test_file_error_does_not_stop_other_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            out = Path(temp) / "out"
            root.mkdir()
            (root / "bad.wav").write_bytes(b"bad")
            (root / "good.wav").write_bytes(b"good")
            calls = []
            stderr = io.StringIO()
            with patch.dict(sys.modules, self.fake_modules(calls)), redirect_stderr(stderr):
                summary = worker.transcribe_media(root, out, "txt", "small", "ru", False, None)

            self.assertEqual(summary["status"], "partial")
            self.assertEqual(summary["files"][0]["error"], "decode failed")
            self.assertTrue((out / "good.wav" / "transcript.txt").exists())
            self.assertNotIn("секретный текст", json.dumps(summary, ensure_ascii=False))
            self.assertIn("bad.wav", stderr.getvalue())
            self.assertNotIn("секретный текст", stderr.getvalue())

    def test_writer_failure_does_not_leave_partial_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            out = Path(temp) / "out"
            root.mkdir()
            (root / "one.wav").write_bytes(b"one")
            calls = []
            modules = self.fake_modules(calls)

            def broken_writer(_format, output_dir):
                def write(_result, _audio_path):
                    (Path(output_dir) / "transcript.txt").write_text("partial", encoding="utf-8")
                    raise RuntimeError("writer failed")
                return write

            modules["whisper"].utils.get_writer = broken_writer
            with patch.dict(sys.modules, modules), redirect_stderr(io.StringIO()):
                summary = worker.transcribe_media(root, out, "all", "small", "ru", False, None)
            self.assertEqual(summary["status"], "error")
            self.assertEqual(summary["files"][0]["error"], "writer failed")
            self.assertEqual(summary["files"][0]["outputs"], [])
            self.assertFalse((out / "one.wav" / "transcript.txt").exists())

    def test_rejects_english_model_and_missing_cuda_before_loading(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            (root / "one.wav").write_bytes(b"one")
            calls = []
            with patch.dict(sys.modules, self.fake_modules(calls)):
                with self.assertRaises(ValueError):
                    worker.transcribe_media(root, Path(temp) / "out", "txt", "small.en", "ru", False, None)
            self.assertEqual(calls, [])
            modules = self.fake_modules(calls)
            modules["torch"] = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))
            with patch.dict(sys.modules, modules):
                with self.assertRaisesRegex(RuntimeError, "CUDA"):
                    worker.transcribe_media(root, Path(temp) / "out", "txt", "small", "ru", False, None)
            self.assertEqual(calls, [])

    def test_list_command_emits_relative_paths_as_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "clip.wav").write_bytes(b"audio")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = worker.main(["list", "--project", str(root)])
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stdout.getvalue()), {"files": ["clip.wav"]})


if __name__ == "__main__":
    unittest.main()
