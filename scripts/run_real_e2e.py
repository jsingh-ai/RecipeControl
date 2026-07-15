"""Run Playwright against real local API/worker/frontend processes."""

import os
import signal
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).parents[1]


def wait_for(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status < 500:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {url}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="recipecontrol-real-e2e-") as directory:
        environment = {
            **os.environ,
            "APP_DATABASE_URL": f"sqlite:///{directory}/app.db",
            "SOURCE_ADAPTER": "fixture",
            "VITE_API_URL": "http://127.0.0.1:8008/api",
            "CORS_ORIGINS": "http://127.0.0.1:5174",
        }
        subprocess.run([str(ROOT / ".venv/bin/alembic"), "upgrade", "head"], cwd=ROOT, env=environment, check=True)
        subprocess.run([str(ROOT / ".venv/bin/python"), "-m", "recipecontrol.seed"], cwd=ROOT, env=environment, check=True)
        processes = [
            subprocess.Popen([str(ROOT / ".venv/bin/uvicorn"), "recipecontrol.api:app", "--host", "127.0.0.1", "--port", "8008"], cwd=ROOT, env=environment),
            subprocess.Popen([str(ROOT / ".venv/bin/recipecontrol-worker"), "--poll-seconds", "0.2"], cwd=ROOT, env=environment),
            subprocess.Popen(["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5174"], cwd=ROOT / "frontend", env=environment),
        ]
        try:
            wait_for("http://127.0.0.1:8008/api/health")
            wait_for("http://127.0.0.1:5174")
            subprocess.run(["npx", "playwright", "test", "-c", "playwright.real.config.ts"], cwd=ROOT / "frontend", env=environment, check=True)
        finally:
            for process in processes:
                process.send_signal(signal.SIGTERM)
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()


if __name__ == "__main__":
    main()
