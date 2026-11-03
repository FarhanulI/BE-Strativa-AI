from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 16379
REDIS_COMMAND = [
    "wsl", "-d", "Ubuntu", "--exec", "redis-server",
    "--bind", REDIS_HOST, "--port", str(REDIS_PORT), "--save", "", "--appendonly", "no",
]  # fmt: skip


def redis_answers() -> bool:
    try:
        with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=1) as connection:
            connection.sendall(b"PING\r\n")
            return connection.recv(16).startswith(b"+PONG")
    except OSError:
        return False


def start_redis() -> subprocess.Popen[bytes] | None:
    if redis_answers():
        print(f"redis: already running on {REDIS_HOST}:{REDIS_PORT}")
        return None
    print("redis: starting via WSL (Ubuntu)")
    process = subprocess.Popen(REDIS_COMMAND)
    for _ in range(30):
        if redis_answers():
            return process
        if process.poll() is not None:
            break
        time.sleep(0.5)
    process.terminate()
    raise SystemExit("redis did not start; see README 'Start Redis' for the WSL and Docker options")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start Redis, migrate, and run the API for dev.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-redis", action="store_true", help="do not start Redis")
    parser.add_argument("--no-migrate", action="store_true", help="skip alembic upgrade")
    parser.add_argument("--no-reload", action="store_true")
    args = parser.parse_args()

    environment = {**os.environ, "APP_ENV": "dev"}
    environment.setdefault("REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}/0")
    redis_process = None if args.no_redis else start_redis()
    try:
        if not args.no_migrate:
            result = subprocess.run(
                [sys.executable, "scripts/migrate.py", "upgrade"],
                cwd=ROOT, env=environment, check=False,
            )  # fmt: skip
            if result.returncode:
                raise SystemExit(result.returncode)
        command = [
            sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(args.port),
        ]  # fmt: skip
        if not args.no_reload:
            command.append("--reload")
        raise SystemExit(subprocess.call(command, cwd=ROOT, env=environment))
    finally:
        if redis_process is not None:
            redis_process.terminate()


if __name__ == "__main__":
    main()
