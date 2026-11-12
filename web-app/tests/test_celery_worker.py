"""The Celery worker must import the Redis transport.

kombu 5.7.0 imports packaging from kombu.transport.redis but only depends
on it through the redis extra. Celery does not install that extra, so a
fresh image crash-loops with ModuleNotFoundError. This loads the worker the
same way `celery -A celery_worker.celery` does and builds the transport
without a running Redis.
"""
import os
import subprocess
import sys
import tempfile
import unittest


class CeleryWorkerImportTests(unittest.TestCase):
    def test_worker_loads_redis_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["SECRET_KEY"] = "test-secret"
            env["DATABASE_URL"] = "sqlite:///" + os.path.join(tmp, "app.db")
            env["AUDIO_STORAGE_PATH"] = os.path.join(tmp, "audio")
            env["REDIS_URL"] = "redis://127.0.0.1:6379/0"
            env["PYTHONUNBUFFERED"] = "1"
            script = (
                "import celery_worker\n"
                "transport = celery_worker.celery.connection().transport\n"
                "if transport.driver_type != 'redis':\n"
                "    raise SystemExit('unexpected transport %s' % transport.driver_type)\n"
                "print('redis-transport-ok')\n"
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(
            result.returncode,
            0,
            result.stdout + "\n" + result.stderr,
        )
        self.assertIn("redis-transport-ok", result.stdout)
        self.assertNotIn("ModuleNotFoundError", result.stderr)


if __name__ == "__main__":
    unittest.main()
