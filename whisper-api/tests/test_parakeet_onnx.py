"""Unit tests for the Parakeet ONNX engine. No model download required.

Loads catalog.py and engines_list.py by path so the admin package's Flask
import is not required.
"""
import importlib.util
import os
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from engines import available_engines, get_engine
from engines.parakeet_onnx_engine import (
    ParakeetOnnxEngine,
    _available_cpus,
    _default_num_threads,
    _num_threads,
    _read_f32,
    _window_f32,
    gpu_provider_available,
    locate_bundle,
    merge_chunk_words,
    repo_for_model,
    resolve_provider,
    words_from_tokens,
)

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


catalog = _load("catalog_under_test", ROOT / "admin" / "catalog.py")
engines_list = _load("engines_list_under_test", ROOT / "admin" / "engines_list.py")
by_id = catalog.by_id
engines_choices = engines_list.engines_choices


class CatalogTests(unittest.TestCase):
    def test_ultra_and_redux_are_catalog_models(self):
        ultra = by_id("parakeet-ultra")
        redux = by_id("parakeet-redux")
        self.assertIsNotNone(ultra)
        self.assertIsNotNone(redux)
        self.assertEqual(ultra.engine, "parakeet_onnx")
        self.assertEqual(redux.engine, "parakeet_onnx")
        self.assertEqual(ultra.repo_id, "erponce/sherpa-onnx-parakeet-ultra-tdt-0.6b-v3-int8")
        self.assertEqual(redux.repo_id, "cohearo/sherpa-onnx-nemo-parakeet-redux")
        self.assertIn("CC-BY-4.0", ultra.description)
        self.assertIn("CC-BY-4.0", redux.description)
        self.assertIn("moondream/parakeet-ultra", ultra.description)
        self.assertIn("moondream/parakeet-redux", redux.description)
        self.assertIn("25", ultra.display_name)
        self.assertIn("25", redux.display_name)
        self.assertIn("653", ultra.size_hint)
        self.assertIn("397", redux.size_hint)

    def test_engine_registry_and_forms(self):
        self.assertIn("parakeet_onnx", available_engines())
        self.assertIs(get_engine("parakeet_onnx"), ParakeetOnnxEngine)
        ids = [row["id"] for row in engines_choices()]
        self.assertEqual(ids, ["whisperx", "nemo", "parakeet_onnx"])
        html = (ROOT / "templates" / "instances.html").read_text()
        self.assertIn("eng.short_label", html)
        self.assertNotIn('choices=["whisperx", "nemo"]', (ROOT / "worker.py").read_text())
        self.assertNotIn('{"whisperx", "nemo"}', (ROOT / "admin" / "api.py").read_text())
        self.assertNotIn('{"whisperx", "nemo"}', (ROOT / "app.py").read_text())
        self.assertIn("available_engines()", (ROOT / "worker.py").read_text())
        self.assertIn("sherpa-onnx==1.13.8", (ROOT / "requirements.txt").read_text())


class BundleTests(unittest.TestCase):
    def test_directory_prefers_int8_per_file(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in (
                "encoder.onnx", "encoder.int8.onnx",
                "decoder.onnx", "joiner.int8.onnx", "tokens.txt",
            ):
                Path(directory, name).write_text("x")
            bundle = locate_bundle(directory)
        self.assertTrue(bundle["encoder"].endswith("encoder.int8.onnx"))
        self.assertTrue(bundle["decoder"].endswith("decoder.onnx"))
        self.assertTrue(bundle["joiner"].endswith("joiner.int8.onnx"))

    def test_cache_hit_skips_download(self):
        calls = []

        def download(repo, hf_home, token):
            calls.append(repo)

        with tempfile.TemporaryDirectory() as home:
            repo = "erponce/sherpa-onnx-parakeet-ultra-tdt-0.6b-v3-int8"
            snap = Path(home) / "hub" / ("models--" + repo.replace("/", "--")) / "snapshots" / "rev"
            snap.mkdir(parents=True)
            for name in ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"):
                (snap / name).write_text("x")
            bundle = locate_bundle(
                "parakeet-ultra", hf_home=home, download_fn=download,
            )
        self.assertEqual(calls, [])
        self.assertTrue(bundle["encoder"].endswith("encoder.int8.onnx"))

    def test_download_on_miss_and_photon_redirect(self):
        calls = []

        def download(repo, hf_home, token):
            calls.append((repo, token))
            snap = Path(hf_home) / "hub" / ("models--" + repo.replace("/", "--")) / "snapshots" / "rev"
            snap.mkdir(parents=True)
            for name in ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt"):
                (snap / name).write_text("x")

        with tempfile.TemporaryDirectory() as home:
            bundle = locate_bundle(
                "moondream/parakeet-redux",
                hf_home=home,
                token="hf_test",
                download_fn=download,
            )
        self.assertEqual(calls, [("cohearo/sherpa-onnx-nemo-parakeet-redux", "hf_test")])
        self.assertTrue(bundle["tokens"].endswith("tokens.txt"))
        self.assertEqual(repo_for_model("parakeet-redux"), "cohearo/sherpa-onnx-nemo-parakeet-redux")

    def test_unknown_model_raises(self):
        with self.assertRaises(RuntimeError):
            repo_for_model("not-a-model")


class TimestampTests(unittest.TestCase):
    def test_leading_space_pieces_become_words(self):
        tokens = [" G", "uten", " Tag", ",", " das"]
        times = [0.0, 0.32, 0.56, 0.80, 1.04]
        words = words_from_tokens(tokens, times)
        self.assertEqual([word["word"] for word in words], ["Guten", "Tag,", "das"])
        self.assertEqual(words[0]["start"], 0.0)
        self.assertEqual(words[0]["end"], 0.56)
        self.assertEqual(words[1]["start"], 0.56)
        self.assertGreater(words[-1]["end"], words[-1]["start"])

    def test_sentencepiece_marker(self):
        words = words_from_tokens(["▁Hallo", "▁Welt"], [0.0, 0.4])
        self.assertEqual([word["word"] for word in words], ["Hallo", "Welt"])
        self.assertEqual(words[0]["end"], 0.4)

    def test_overlap_seam_keeps_each_sides_half(self):
        previous = [
            {"word": "eins", "start": 27.0, "end": 27.4},
            {"word": "zwei", "start": 29.2, "end": 29.6},
        ]
        new_words = [
            {"word": "zwei", "start": 29.1, "end": 29.5},
            {"word": "drei", "start": 30.2, "end": 30.6},
        ]
        # chunk starts at 28s, overlap 2s → seam at 29s
        kept = merge_chunk_words(previous, new_words, chunk_start=28.0, overlap=2.0)
        self.assertEqual([word["word"] for word in previous], ["eins"])
        self.assertEqual([word["word"] for word in kept], ["zwei", "drei"])

    def test_empty_new_words_do_not_delete_the_tail(self):
        previous = [{"word": "bleibt", "start": 29.2, "end": 29.6}]
        kept = merge_chunk_words(previous, [], chunk_start=28.0, overlap=2.0)
        self.assertEqual(kept, [])
        self.assertEqual(previous[0]["word"], "bleibt")


class ProviderTests(unittest.TestCase):
    def test_cuda_without_gpu_build_falls_back(self):
        provider, note = resolve_provider("cuda", gpu_available=False)
        self.assertEqual(provider, "cpu")
        self.assertIn("CPU", note)

    def test_cuda_with_gpu_build(self):
        provider, note = resolve_provider("cuda:0", gpu_available=True)
        self.assertEqual(provider, "cuda")
        self.assertIsNone(note)

    def test_mps_is_cpu(self):
        provider, note = resolve_provider("mps", gpu_available=True)
        self.assertEqual(provider, "cpu")
        self.assertIn("MPS", note)

    def test_override_cpu(self):
        provider, note = resolve_provider("cuda", gpu_available=True, override="cpu")
        self.assertEqual(provider, "cpu")
        self.assertIn("PARAKEET_ONNX_PROVIDER=cpu", note)

    def test_installed_wheel_is_cpu_only(self):
        try:
            import sherpa_onnx  # noqa: F401
        except ImportError:
            self.skipTest("sherpa-onnx is not installed")
        self.assertFalse(gpu_provider_available())


class EngineContractTests(unittest.TestCase):
    def test_language_is_not_forced_and_segments_keep_words(self):
        engine = ParakeetOnnxEngine(model="parakeet-ultra", device="cpu", compute_type="float16")

        def decode(_rate, _samples):
            return "Guten Tag.", [
                {"word": "Guten", "start": 0.0, "end": 0.4},
                {"word": "Tag.", "start": 0.4, "end": 0.8},
            ]

        engine._recognizer = object()
        engine._decode_samples = decode
        # Bypass ffmpeg: the unit stand-in already returns words.
        import engines.parakeet_onnx_engine as mod
        import numpy as np
        original = mod._to_mono_wav
        original_read = mod._read_f32
        mod._to_mono_wav = lambda _path: ("/tmp/unused.wav", False)
        mod._read_f32 = lambda _path: (16000, np.zeros(16000, dtype=np.float32))
        try:
            os.environ["PARAKEET_ONNX_CHUNK_SECS"] = "30"
            result = engine.transcribe("/tmp/clip.wav", language="de")
        finally:
            mod._to_mono_wav = original
            mod._read_f32 = original_read
        self.assertEqual(result.language, "de")
        self.assertEqual(result.text, "Guten Tag.")
        self.assertEqual(result.segments[0]["text"], "Guten Tag.")
        self.assertIn("words", result.segments[0])
        self.assertFalse(engine.supports_alignment)
        self.assertTrue(engine.supports_diarization)

    def test_short_and_long_audio_log_duration_phases_and_rtf(self):
        import engines.parakeet_onnx_engine as mod

        engine = ParakeetOnnxEngine(model="parakeet-ultra", device="cpu", compute_type="int8")
        engine._recognizer = object()
        engine._decode_samples = lambda _rate, _samples: ("Hallo", [{"word": "Hallo", "start": 0.0, "end": 0.2}])
        original_wav = mod._to_mono_wav
        original_read = mod._read_f32
        mod._to_mono_wav = lambda _path: ("/tmp/unused.wav", False)
        try:
            mod._read_f32 = lambda _path: (16000, np.zeros(16000, dtype=np.float32))
            os.environ["PARAKEET_ONNX_CHUNK_SECS"] = "30"
            with self.assertLogs("whisper-api.engine.parakeet_onnx", level="INFO") as short_logs:
                engine.transcribe("/tmp/clip.wav", language="de")
            short_text = "\n".join(short_logs.output)
            self.assertIn("Audio is 1.00s", short_text)
            self.assertIn("convert=", short_text)
            self.assertIn("decode=", short_text)
            self.assertIn("diarize=0.000s", short_text)
            self.assertIn("rtf=", short_text)

            mod._read_f32 = lambda _path: (16000, np.zeros(16000 * 70, dtype=np.float32))
            seen = []

            def decode(rate, samples):
                seen.append(int(len(samples)))
                return "x", [{"word": "x", "start": 0.0, "end": 0.1}]

            engine._decode_samples = decode
            os.environ["PARAKEET_ONNX_CHUNK_OVERLAP_SECS"] = "2"
            with self.assertLogs("whisper-api.engine.parakeet_onnx", level="INFO") as long_logs:
                engine.transcribe("/tmp/long.wav", language="de")
            long_text = "\n".join(long_logs.output)
            self.assertIn("Audio is 70.00s", long_text)
            self.assertIn("rtf=", long_text)
            self.assertIn("window(s)", long_text)
            # 30 s windows + 2 s overlap; the tail is the last 10 s.
            self.assertEqual(seen, [16000 * 32, 16000 * 32, 16000 * 10])
        finally:
            mod._to_mono_wav = original_wav
            mod._read_f32 = original_read
            os.environ.pop("PARAKEET_ONNX_CHUNK_OVERLAP_SECS", None)


def _legacy_ffmpeg_f32(src: str, start: float, length: float):
    """The 1.4.1 window path: one ffmpeg WAV plus a Python float per sample."""
    fd, dst = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
                "-i", src,
                "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                dst,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        with wave.open(dst, "rb") as handle:
            raw = handle.readframes(handle.getnframes())
    finally:
        try:
            os.unlink(dst)
        except OSError:
            pass
    import array
    import sys
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    return [sample / 32768.0 for sample in samples]


class ThreadDefaultTests(unittest.TestCase):
    def setUp(self):
        import engines.parakeet_onnx_engine as mod
        self.mod = mod
        self._env = os.environ.get("PARAKEET_ONNX_NUM_THREADS")
        os.environ.pop("PARAKEET_ONNX_NUM_THREADS", None)
        self._logged = mod._logged_thread_choice
        self._cpus = mod._available_cpus
        mod._logged_thread_choice = None

    def tearDown(self):
        if self._env is None:
            os.environ.pop("PARAKEET_ONNX_NUM_THREADS", None)
        else:
            os.environ["PARAKEET_ONNX_NUM_THREADS"] = self._env
        self.mod._logged_thread_choice = self._logged
        self.mod._available_cpus = self._cpus

    def test_half_of_available_capped_at_8(self):
        self.assertEqual(_default_num_threads(1), (1, False))
        self.assertEqual(_default_num_threads(2), (1, False))
        self.assertEqual(_default_num_threads(4), (2, False))
        self.assertEqual(_default_num_threads(7), (3, False))
        self.assertEqual(_default_num_threads(16), (8, False))
        self.assertEqual(_default_num_threads(18), (8, True))
        self.assertEqual(_default_num_threads(32), (8, True))

    def test_explicit_value_overrides_cap(self):
        os.environ["PARAKEET_ONNX_NUM_THREADS"] = "12"
        self.mod._available_cpus = lambda: 4
        with self.assertLogs("whisper-api.engine.parakeet_onnx", level="INFO") as logs:
            self.assertEqual(_num_threads(), 12)
        self.assertIn("PARAKEET_ONNX_NUM_THREADS", "\n".join(logs.output))
        self.assertNotIn("cap 8 applies", "\n".join(logs.output))

    def test_cap_is_logged_when_it_reduces_the_half(self):
        self.mod._available_cpus = lambda: 32
        with self.assertLogs("whisper-api.engine.parakeet_onnx", level="INFO") as logs:
            self.assertEqual(_num_threads(), 8)
        text = "\n".join(logs.output)
        self.assertIn("threads=8", text)
        self.assertIn("available CPUs=32", text)
        self.assertIn("cap 8 applies", text)

    def test_invalid_override_falls_back_to_default(self):
        os.environ["PARAKEET_ONNX_NUM_THREADS"] = "many"
        self.mod._available_cpus = lambda: 10
        with self.assertLogs("whisper-api.engine.parakeet_onnx", level="WARNING") as logs:
            self.assertEqual(_num_threads(), 5)
        self.assertIn("not an integer", "\n".join(logs.output))

    def test_affinity_failure_uses_cpu_count(self):
        original_affinity = getattr(os, "sched_getaffinity", None)
        original_count = os.cpu_count

        def boom(_pid):
            raise OSError("affinity unavailable")

        os.sched_getaffinity = boom
        os.cpu_count = lambda: 6
        try:
            self.assertEqual(_available_cpus(), 6)
        finally:
            if original_affinity is None:
                del os.sched_getaffinity
            else:
                os.sched_getaffinity = original_affinity
            os.cpu_count = original_count


class WindowSliceTests(unittest.TestCase):
    def test_numpy_windows_match_ffmpeg_and_python_floats(self):
        if subprocess.call(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
            self.skipTest("ffmpeg is not installed")
        rate = 16000
        n = rate * 8
        pcm = ((np.arange(n, dtype=np.int32) * 17 + 12345) % 65536 - 32768).astype("<i2")
        fd, src = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            with wave.open(src, "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(rate)
                handle.writeframes(pcm.tobytes())
            got_rate, samples = _read_f32(src)
            self.assertEqual(got_rate, rate)
            legacy_full = np.array(
                [int(sample) / 32768.0 for sample in np.frombuffer(pcm.tobytes(), dtype="<i2").tolist()],
                dtype=np.float64,
            )
            self.assertEqual(samples.shape, legacy_full.shape)
            self.assertEqual(float(np.max(np.abs(legacy_full - samples))), 0.0)

            duration = n / rate
            chunk, overlap = 3.0, 0.5
            starts = []
            cursor = 0.0
            while cursor < duration - 1e-3:
                starts.append(cursor)
                cursor += chunk
            if len(starts) > 1 and duration - starts[-1] <= overlap:
                starts.pop()
            self.assertGreaterEqual(len(starts), 2)
            for start in starts:
                length = min(chunk + overlap, max(0.0, duration - start))
                legacy = np.asarray(_legacy_ffmpeg_f32(src, start, length), dtype=np.float64)
                window = _window_f32(samples, rate, start, length)
                self.assertEqual(legacy.shape, window.shape, msg=f"start={start} length={length}")
                self.assertEqual(float(np.max(np.abs(legacy - window))), 0.0)
        finally:
            os.unlink(src)


if __name__ == "__main__":
    unittest.main()
