import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_ready(base_url: str, process: subprocess.Popen, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"'flask run' exited early:\n{output}")
        try:
            urllib.request.urlopen(base_url, timeout=1)
            return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.3)
    process.kill()
    raise RuntimeError(f"'flask run' did not become ready within {timeout}s")


@pytest.fixture(scope="session")
def live_server_url(dynamodb_table, eventbridge_bus_and_queues, cognito_pool, aws_endpoints):
    # cognito_pool must resolve (and set its 3 env vars) before os.environ is
    # copied below for the flask run subprocess -- listing it as a parameter
    # here forces that ordering.
    port = _free_port()
    env = os.environ.copy()
    env["FLASK_APP"] = "app.main:app"

    process = subprocess.Popen(
        [sys.executable, "-m", "flask", "run", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_until_ready(base_url, process)
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
