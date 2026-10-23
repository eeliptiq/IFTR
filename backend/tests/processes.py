"""
Starting and stopping the servers the opt-in tests drive.

Two suites bring up real processes: the browser journeys start uvicorn and
`craco start`, and the crypto burn-in starts uvicorn beside two containers. The
part that is easy to get wrong is not either of them - it is shutting a server
down without leaving npm's node child behind, and saying what a process printed
when it never came up. That part lives here.

Nothing in the ordinary suite imports this; a test that wants it is asking for a
process, and those tests are all behind their own environment variable.
"""

import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Dict, List

import httpx


def free_port() -> int:
    """A port nothing is listening on, for this run only."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def tail(path: Path, lines: int = 40) -> str:
    try:
        return "\n".join(
            path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
        )
    except OSError:
        return f"<no log at {path}>"


def wait_for(url: str, timeout: float, process: subprocess.Popen, log: Path) -> None:
    """Poll until the URL answers, or say what the process printed instead."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(
                f"{url} never came up: the process exited with {process.returncode}\n"
                f"--- {log} ---\n{tail(log)}"
            )
        try:
            if httpx.get(url, timeout=5.0).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)

    raise AssertionError(
        f"{url} did not answer within {timeout:.0f}s\n--- {log} ---\n{tail(log)}"
    )


def stop(process: subprocess.Popen) -> None:
    """Stop a server and the children it spawned (npm keeps a node child)."""
    if process.poll() is not None:
        return

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
        return

    try:
        os.killpg(os.getpgid(process.pid), 15)
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(process.pid), 9)


def spawn(
    command: List[str], cwd: Path, env: Dict[str, str], log: Path
) -> subprocess.Popen:
    """Start a server with its output in a file, in its own process group."""
    handle = log.open("w", encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603 - fixed commands, no shell
        command,
        cwd=str(cwd),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    # The child owns the description now; the test only reads the file.
    handle.close()
    return process
