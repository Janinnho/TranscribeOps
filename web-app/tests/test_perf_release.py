"""Focused checks for the 1.5.0 web-app performance changes."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app.tasks as tasks


class PollBackoffTests(unittest.TestCase):
    def test_starts_fast_and_caps_at_two_seconds(self):
        intervals = [tasks._poll_backoff_interval(i) for i in range(6)]
        self.assertEqual(intervals, [0.25, 0.5, 1.0, 2.0, 2.0, 2.0])

    def test_negative_attempt_uses_the_initial_interval(self):
        self.assertEqual(tasks._poll_backoff_interval(-3), 0.25)


class FfmpegSeekTests(unittest.TestCase):
    def test_seek_is_an_input_option(self):
        args = tasks._ffmpeg_cut_args("meeting.webm", 12.5, 3.25, "chunk.mp3")
        self.assertLess(args.index("-ss"), args.index("-i"))
        self.assertLess(args.index("-i"), args.index("-t"))
        self.assertEqual(args[args.index("-ss") + 1], "12.5")
        self.assertEqual(args[args.index("-i") + 1], "meeting.webm")
        self.assertEqual(args[args.index("-t") + 1], "3.25")
        self.assertEqual(args[-1], "chunk.mp3")


class DurationProbeTests(unittest.TestCase):
    def test_tiny_file_cannot_reach_the_limit(self):
        # 1 kbit/s * 600 s = 75_000 bytes. A 100-byte clip cannot be longer.
        self.assertFalse(tasks._may_exceed_duration(100, 600))
        self.assertFalse(tasks._may_exceed_duration(600 * 125, 600))

    def test_larger_file_is_probed(self):
        self.assertTrue(tasks._may_exceed_duration(600 * 125 + 1, 600))

    def test_no_limit_skips_the_check(self):
        self.assertFalse(tasks._may_exceed_duration(50_000_000, 0))

    def test_short_upload_does_not_split(self):
        model = SimpleNamespace(
            provider="whisper_local",
            max_file_size_mb=0,
            max_duration_secs=600,
        )
        fd, path = tempfile.mkstemp(suffix=".webm")
        os.write(fd, b"x" * 100)
        os.close(fd)
        try:
            with patch.object(tasks, "_split_audio_file", side_effect=AssertionError("ffprobe")), \
                    patch.object(tasks, "_whisper_local_async", return_value="ok") as call:
                result = tasks._call_speech_api(
                    model, path, original_filename="note.webm",
                )
            self.assertEqual(result, "ok")
            self.assertEqual(call.call_args.args[3], "note.webm")
        finally:
            os.unlink(path)


class ChunkUploadTests(unittest.TestCase):
    def test_split_chunks_are_sent_as_mp3(self):
        model = SimpleNamespace(
            provider="whisper_local",
            max_file_size_mb=0,
            max_duration_secs=1,
            supports_diarize=False,
        )
        fd, path = tempfile.mkstemp(suffix=".webm")
        os.write(fd, b"x" * 500)
        os.close(fd)
        chunks = [path + "_chunk000.mp3", path + "_chunk001.mp3"]
        seen = []

        def fake_async(model, file_path, language, original_filename, dictionary_prompt, progress_callback=None):
            seen.append((file_path, original_filename))
            filename, mime = tasks._get_file_info(file_path, original_filename)
            self.assertTrue(filename.endswith(".mp3"))
            self.assertEqual(mime, "audio/mpeg")
            return {"text": "teil"}

        try:
            with patch.object(tasks, "_split_audio_file", return_value=chunks), \
                    patch.object(tasks, "_whisper_local_async", side_effect=fake_async):
                result = tasks._call_speech_api(
                    model, path, original_filename="meeting.webm",
                )
            self.assertEqual(result, "teil teil")
            self.assertEqual([name for _, name in seen], [os.path.basename(chunk) for chunk in chunks])
            self.assertTrue(all(name.endswith(".mp3") for _, name in seen))
            self.assertNotIn("meeting.webm", [name for _, name in seen])
        finally:
            os.unlink(path)


class GetAppTests(unittest.TestCase):
    def tearDown(self):
        tasks._worker_app = None

    def test_create_app_runs_once_per_process(self):
        tasks._worker_app = None
        sentinel = object()
        with patch("app.create_app", return_value=sentinel) as create:
            first = tasks.get_app()
            second = tasks.get_app()
        self.assertIs(first, sentinel)
        self.assertIs(second, sentinel)
        self.assertEqual(create.call_count, 1)


if __name__ == "__main__":
    unittest.main()
