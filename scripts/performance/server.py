"""Start or stop only the performance gunicorn master, preserving the heavy gate."""

import argparse
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

PID_FILE = Path(".cache/performance/gunicorn.pid")


def main():
    """Manage the recorded master PID and show the loopback listener state."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop"])
    args = parser.parse_args()
    if args.action == "start":
        if PID_FILE.exists():
            raise RuntimeError("A recorded gunicorn PID already exists")
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        # A daemon must not retain heavy's semaphore fd after its launcher exits.
        subprocess.run(
            [
                ".venv/bin/gunicorn",
                "credit_mate_ai.wsgi:application",
                "--workers",
                "3",
                "--bind",
                "127.0.0.1:8020",
                "--daemon",
                "--pid",
                str(PID_FILE),
                "--error-logfile",
                ".cache/performance/gunicorn.log",
            ],
            check=True,
            close_fds=True,
        )
        for _ in range(100):
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:8020/health/", timeout=1
                ) as response:
                    if response.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError("Gunicorn did not become ready; stop the recorded PID")
        print("Started gunicorn PID", PID_FILE.read_text().strip())
    else:
        pid = int(PID_FILE.read_text())
        os.kill(pid, signal.SIGTERM)
        for _ in range(100):
            if not PID_FILE.exists():
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Gunicorn did not stop")
        print("Stopped gunicorn PID", pid)
    subprocess.run(["ss", "-ltnp", "sport = :8020"], check=True)


if __name__ == "__main__":
    main()
