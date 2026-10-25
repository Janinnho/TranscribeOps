"""Unit tests for the Parakeet ONNX engine. No model download required.

Loads catalog.py and engines_list.py by path so the admin package's Flask
import is not required.
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from engines import available_engines, get_engine
from engines.parakeet_onnx_engine import (
    ParakeetOnnxEngine,
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

        def decode(_path):
            return "Guten Tag.", [
                {"word": "Guten", "start": 0.0, "end": 0.4},
                {"word": "Tag.", "start": 0.4, "end": 0.8},
            ]

        engine._recognizer = object()
        engine._decode_wav = decode
        # Bypass ffmpeg: the unit stand-in already returns words.
        import engines.parakeet_onnx_engine as mod
        original = mod._to_mono_wav
        mod._to_mono_wav = lambda _path: ("/tmp/unused.wav", False)
        try:
            os.environ["PARAKEET_ONNX_CHUNK_SECS"] = "30"
            result = engine.transcribe("/tmp/clip.wav", language="de")
        finally:
            mod._to_mono_wav = original
        self.assertEqual(result.language, "de")
        self.assertEqual(result.text, "Guten Tag.")
        self.assertEqual(result.segments[0]["text"], "Guten Tag.")
        self.assertIn("words", result.segments[0])
        self.assertFalse(engine.supports_alignment)
        self.assertTrue(engine.supports_diarization)


if __name__ == "__main__":
    unittest.main()
