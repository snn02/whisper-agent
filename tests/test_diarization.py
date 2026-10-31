import unittest
from container import diarization


class DiarizationContractTests(unittest.TestCase):
    def test_splits_speakers_preserves_words_and_overlap_turns(self):
        original = {"language": "ru", "segments": [{"start": 0, "end": 3, "text": " Привет. Да. Неясно.", "words": [
            {"start": 0, "end": 1, "word": " Привет."},
            {"start": 1, "end": 2, "word": " Да."},
            {"start": 2, "end": 3, "word": " Неясно."},
        ]}]}
        result = diarization.build_document(original, [(0, 1.2, "a"), (0.9, 2, "b")], [(0, 1, "a"), (1, 2, "b")], "call.wav")
        self.assertEqual([s["speaker_id"] for s in result["segments"]], ["Speaker1", "Speaker2", None])
        self.assertEqual("".join(s["text"] for s in result["segments"]), original["segments"][0]["text"])
        self.assertEqual(result["turns"][0]["end"], 1.2)
        self.assertEqual(result["turns"][1]["start"], 0.9)
        self.assertEqual(len({s["id"] for s in result["segments"]}), 3)

    def test_tie_short_overlap_and_zero_duration_are_unknown(self):
        for turns in [[(0, 0.5, "a"), (0.5, 1, "b")], [(0, 0.1, "a")], []]:
            self.assertIsNone(diarization.choose_speaker(0, 1, turns))
        self.assertIsNone(diarization.choose_speaker(1, 1, [(0, 2, "a")]))

    def test_missing_or_incomplete_word_timings_do_not_drop_text(self):
        for words in [[], [{"word": "часть", "start": 0, "end": 0.5}]]:
            original = {"language": "ru", "segments": [{"start": 0, "end": 1, "text": "часть текста", "words": words}]}
            result = diarization.build_document(original, [(0, 1, "a")], [(0, 1, "a")], "x.wav")
            self.assertEqual(result["segments"][0]["text"], "часть текста")
            self.assertIsNone(result["segments"][0]["speaker_id"])

    def test_empty_audio_contract(self):
        result = diarization.build_document({"language": "ru", "segments": []}, [], [], "empty.wav")
        self.assertEqual(result["speakers"], [])
        self.assertEqual(result["segments"], [])


if __name__ == "__main__":
    unittest.main()
