"""Deleting a catalog model's local HuggingFace cache.

The cache delete must only remove that repo's directory, must not follow
symlinks, and the admin API must refuse while an instance still uses it.
"""
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# admin.api imports the engine registry, which pulls Whisper/NeMo. The delete
# path never calls an engine, so a stub is enough to load the blueprint.
if "engines" not in sys.modules:
    _engines = types.ModuleType("engines")
    _engines.EngineBusy = type("EngineBusy", (Exception,), {})
    _engines.EngineUnavailable = type("EngineUnavailable", (Exception,), {})
    _engines.available_engines = lambda: ["whisperx", "nemo", "parakeet_onnx"]
    _engines.get_engine = lambda name: None
    sys.modules["engines"] = _engines

from admin import create_admin_blueprint, db as admin_db
from admin import downloads


TINY_REPO = "Systran/faster-whisper-tiny"
TINY_SLUG = "models--Systran--faster-whisper-tiny"


def _use_cache(home: Path):
    downloads.HF_HOME_DIR = str(home)
    downloads.HF_CACHE_DIR = str(home / "hub")


def _write_snapshot(base: Path, payload: bytes = b"weights") -> Path:
    snap = base / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "model.bin").write_bytes(payload)
    return snap


class RemoveCachedRepoTests(unittest.TestCase):
    def test_hub_and_legacy_copies_are_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _use_cache(home)
            hub = home / "hub" / TINY_SLUG
            legacy = home / TINY_SLUG
            _write_snapshot(hub, b"a" * 32)
            _write_snapshot(legacy, b"b" * 32)
            sibling = home / "hub" / "models--Systran--faster-whisper-base"
            _write_snapshot(sibling, b"keep")

            self.assertTrue(downloads.is_downloaded(TINY_REPO))
            self.assertTrue(downloads.remove_cached_repo(TINY_REPO))
            self.assertFalse(downloads.is_downloaded(TINY_REPO))
            self.assertFalse(hub.exists())
            self.assertFalse(legacy.exists())
            self.assertTrue((sibling / "snapshots" / "abc" / "model.bin").is_file())

    def test_unknown_repo_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _use_cache(home)
            planted = home / "hub" / "models--..--.."
            planted.mkdir(parents=True)
            (planted / "secret").write_text("keep")
            with self.assertRaises(ValueError):
                downloads.remove_cached_repo("../../etc")
            self.assertTrue((planted / "secret").is_file())

    def test_symlink_repo_dir_is_unlinked_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _use_cache(home)
            outside = home / "outside"
            outside.mkdir()
            (outside / "secret").write_text("keep")
            link = home / "hub" / TINY_SLUG
            link.parent.mkdir(parents=True)
            link.symlink_to(outside, target_is_directory=True)
            self.assertTrue(downloads.remove_cached_repo(TINY_REPO))
            self.assertFalse(link.exists() or link.is_symlink())
            self.assertEqual((outside / "secret").read_text(), "keep")

    def test_symlink_inside_snapshot_is_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _use_cache(home)
            outside = home / "outside-file"
            outside.write_text("keep")
            snap = _write_snapshot(home / "hub" / TINY_SLUG)
            (snap / "linked").symlink_to(outside)
            downloads.remove_cached_repo(TINY_REPO)
            self.assertFalse((home / "hub" / TINY_SLUG).exists())
            self.assertEqual(outside.read_text(), "keep")

    def test_missing_cache_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            _use_cache(Path(tmp))
            self.assertFalse(downloads.remove_cached_repo(TINY_REPO))
            self.assertFalse(downloads.is_downloaded(TINY_REPO))


class ModelDeleteApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "hf"
        self.home.mkdir()
        _use_cache(self.home)
        self.db_path = str(Path(self.tmp.name) / "admin.db")
        admin_db.init_db(self.db_path)
        self.main = {
            "loaded": False,
            "disabled": False,
            "config": {"engine": "whisperx", "model": "small", "device": "cpu", "compute_type": "int8"},
            "reload": {"status": "idle", "error": None},
            "port": 8000,
        }
        from flask import Flask
        from flask_babel import Babel
        app = Flask(__name__)
        app.secret_key = "test"
        Babel(app, locale_selector=lambda: "en")
        app.register_blueprint(
            create_admin_blueprint(
                db_path=self.db_path,
                admin_password="test-admin",
                hf_token="",
                default_device="cpu",
                default_compute_type="int8",
                port_range="8100-8120",
                main_engine_state=lambda: self.main,
            ),
            url_prefix="/admin",
        )
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["admin"] = True

    def tearDown(self):
        self.tmp.cleanup()

    def _cache_tiny(self):
        _write_snapshot(self.home / "hub" / TINY_SLUG)

    def test_delete_clears_downloaded_status(self):
        self._cache_tiny()
        self.assertTrue(downloads.is_downloaded(TINY_REPO))
        res = self.client.delete("/admin/api/models/tiny")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["downloaded"])
        self.assertFalse(downloads.is_downloaded(TINY_REPO))

    def test_delete_requires_login(self):
        self._cache_tiny()
        with self.client.session_transaction() as sess:
            sess.clear()
        res = self.client.delete("/admin/api/models/tiny")
        self.assertEqual(res.status_code, 401)
        self.assertTrue(downloads.is_downloaded(TINY_REPO))

    def test_unknown_model_is_404(self):
        res = self.client.delete("/admin/api/models/not-a-model")
        self.assertEqual(res.status_code, 404)

    def test_refuses_while_an_instance_uses_the_model(self):
        self._cache_tiny()
        admin_db.create_instance(
            self.db_path,
            name="express",
            engine="whisperx",
            model="tiny",
            purpose="transcription",
            device="cpu",
            compute_type="int8",
            port=8100,
            enabled=0,
        )
        res = self.client.delete("/admin/api/models/tiny")
        self.assertEqual(res.status_code, 409)
        self.assertIn("express", res.get_json()["error"])
        self.assertTrue(downloads.is_downloaded(TINY_REPO))

    def test_refuses_while_the_main_engine_uses_the_model(self):
        self._cache_tiny()
        self.main["config"]["model"] = "tiny"
        res = self.client.delete("/admin/api/models/tiny")
        self.assertEqual(res.status_code, 409)
        self.assertTrue(downloads.is_downloaded(TINY_REPO))

    def test_refuses_while_a_download_is_running(self):
        self._cache_tiny()
        admin_db.create_download(self.db_path, TINY_REPO, "whisper")
        # create_download inserts status 'pending', which counts as active.
        res = self.client.delete("/admin/api/models/tiny")
        self.assertEqual(res.status_code, 409)
        self.assertTrue(downloads.is_downloaded(TINY_REPO))


if __name__ == "__main__":
    unittest.main()
