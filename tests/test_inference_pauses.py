import io
import os
import tempfile
import unittest
import wave
from unittest.mock import patch

from inference import TTSClient, combine_wav_segments, make_silent_wav, split_pause_text


class PauseTextTests(unittest.TestCase):
    def test_half_and_full_width_spaces_accumulate(self):
        self.assertEqual(
            split_pause_text("甲 　乙"),
            [("speech", "甲"), ("pause", 2), ("speech", "乙")],
        )

    def test_leading_trailing_and_consecutive_spaces_are_preserved(self):
        self.assertEqual(
            split_pause_text("  甲   乙 "),
            [("pause", 2), ("speech", "甲"), ("pause", 3), ("speech", "乙"), ("pause", 1)],
        )

    def test_newlines_are_not_pause_events(self):
        self.assertEqual(
            split_pause_text("甲\n乙"),
            [("speech", "甲\n乙")],
        )


class WavPauseTests(unittest.TestCase):
    def test_combined_wav_keeps_format_and_adds_silence(self):
        first_speech = make_silent_wav(0.25, sample_rate=8000, channels=1, sample_width=2)
        second_speech = make_silent_wav(0.5, sample_rate=8000, channels=1, sample_width=2)
        combined = combine_wav_segments(
            [("pause", 1), ("speech", first_speech), ("pause", 2), ("speech", second_speech)]
        )

        with wave.open(io.BytesIO(combined), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 8000)
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.getnframes(), 30000)

    def test_only_spaces_create_silent_wav(self):
        combined = combine_wav_segments([("pause", 1), ("pause", 2)])

        with wave.open(io.BytesIO(combined), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 32000)
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.getnframes(), 96000)
            self.assertEqual(wav_file.readframes(wav_file.getnframes()), b"\x00" * 192000)

    def test_client_requests_each_speech_segment(self):
        class Response:
            status_code = 200
            text = ""

            def __init__(self):
                self.content = make_silent_wav(0.25, sample_rate=8000)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def iter_content(self, chunk_size):
                yield self.content

        responses = [Response(), Response()]
        with tempfile.TemporaryDirectory() as temp_dir:
            save_path = os.path.join(temp_dir, "output.wav")
            with patch.object(TTSClient, "is_api_running", return_value=True), patch(
                "inference.requests.post", side_effect=responses
            ) as request:
                success, _ = TTSClient().generate_speech("甲　乙", save_path)

            self.assertTrue(success)
            self.assertEqual([call.kwargs["json"]["text"] for call in request.call_args_list], ["甲", "乙"])
            with wave.open(save_path, "rb") as wav_file:
                self.assertEqual(wav_file.getnframes(), 12000)


if __name__ == "__main__":
    unittest.main()
