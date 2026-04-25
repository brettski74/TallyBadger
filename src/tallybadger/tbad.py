from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time


@dataclass(frozen=True)
class TbadConfig:
    run_dir: Path
    log_dir: Path
    api_cmd: str
    frontend_cmd: str
    db_up_cmd: str
    db_down_cmd: str
    db_status_cmd: str
    db_logs_cmd: str


def load_config() -> TbadConfig:
    return TbadConfig(
        run_dir=Path(os.environ.get("TBAD_RUN_DIR", "local/run")),
        log_dir=Path(os.environ.get("TBAD_LOG_DIR", "local/logs")),
        api_cmd=os.environ.get(
            "TBAD_API_CMD",
            ".venv/bin/uvicorn tallybadger.main:app --reload --host 127.0.0.1 --port 8080",
        ),
        frontend_cmd=os.environ.get(
            "TBAD_FRONTEND_CMD",
            "npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173",
        ),
        db_up_cmd=os.environ.get("TBAD_DB_UP_CMD", "docker compose up -d db"),
        db_down_cmd=os.environ.get("TBAD_DB_DOWN_CMD", "docker compose down"),
        db_status_cmd=os.environ.get("TBAD_DB_STATUS_CMD", "docker compose ps db"),
        db_logs_cmd=os.environ.get("TBAD_DB_LOGS_CMD", "docker compose logs db"),
    )


def pid_file(run_dir: Path, service: str) -> Path:
    return run_dir / f"{service}.pid"


def log_file(log_dir: Path, service: str) -> Path:
    return log_dir / f"{service}.log"


def is_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def run_command(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        shlex.split(command),
        check=False,
        text=True,
        capture_output=True,
    )


def ensure_running(service: str, command: str, config: TbadConfig) -> None:
    config.run_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    pid_path = pid_file(config.run_dir, service)
    existing_pid = read_pid(pid_path)
    if existing_pid and is_pid_running(existing_pid):
        print(f"{service}: already running (pid {existing_pid})")
        return

    logfile_path = log_file(config.log_dir, service)
    with logfile_path.open("a", encoding="utf-8") as handle:
        process = subprocess.Popen(  # noqa: S603
            shlex.split(command),
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    print(f"{service}: started (pid {process.pid})")


def stop_service(service: str, config: TbadConfig) -> None:
    pid_path = pid_file(config.run_dir, service)
    pid = read_pid(pid_path)
    if pid is None:
        print(f"{service}: not running")
        return
    if not is_pid_running(pid):
        print(f"{service}: stale pid {pid}, cleaning up")
        pid_path.unlink(missing_ok=True)
        return

    os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        if not is_pid_running(pid):
            break
        time.sleep(0.1)
    if is_pid_running(pid):
        os.kill(pid, signal.SIGKILL)
    pid_path.unlink(missing_ok=True)
    print(f"{service}: stopped")


def print_status(config: TbadConfig) -> None:
    for service in ("api", "frontend"):
        pid = read_pid(pid_file(config.run_dir, service))
        if pid and is_pid_running(pid):
            print(f"{service}: running (pid {pid})")
        elif pid:
            print(f"{service}: stale pid ({pid})")
        else:
            print(f"{service}: stopped")

    db_status = run_command(config.db_status_cmd)
    db_text = (db_status.stdout + db_status.stderr).strip()
    if db_status.returncode == 0 and ("Up" in db_text or "running" in db_text.lower()):
        print("db: running")
    elif db_status.returncode == 0:
        print("db: stopped")
    else:
        print("db: unknown")


def print_logs(service: str | None, config: TbadConfig, follow: bool) -> int:
    if service == "db":
        cmd = f"{config.db_logs_cmd} {'-f' if follow else ''}".strip()
        result = subprocess.run(shlex.split(cmd), check=False)  # noqa: S603
        return result.returncode

    services = ("api", "frontend") if service is None else (service,)
    for name in services:
        path = log_file(config.log_dir, name)
        print(f"== {name} log: {path} ==")
        if not path.exists():
            print("(no log file yet)")
            continue
        if follow:
            result = subprocess.run(["tail", "-n", "100", "-f", str(path)], check=False)
            return result.returncode
        print(path.read_text(encoding="utf-8")[-8000:])
    return 0


def command_up(config: TbadConfig) -> int:
    db_up = run_command(config.db_up_cmd)
    if db_up.returncode != 0:
        sys.stderr.write(db_up.stderr or db_up.stdout)
        return db_up.returncode

    ensure_running("api", config.api_cmd, config)
    ensure_running("frontend", config.frontend_cmd, config)
    return 0


def command_down(config: TbadConfig) -> int:
    stop_service("api", config)
    stop_service("frontend", config)
    db_down = run_command(config.db_down_cmd)
    if db_down.returncode != 0:
        sys.stderr.write(db_down.stderr or db_down.stdout)
        return db_down.returncode
    print("db: stopped")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TallyBadger lifecycle CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("up", help="Start app stack in current environment")
    sub.add_parser("down", help="Stop app stack in current environment")
    sub.add_parser("restart", help="Restart app stack in current environment")
    sub.add_parser("status", help="Show service status")

    logs = sub.add_parser("logs", help="Show logs for api/frontend/db")
    logs.add_argument("service", nargs="?", choices=["api", "frontend", "db"])
    logs.add_argument("-f", "--follow", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config()

    if args.command == "up":
        raise SystemExit(command_up(config))
    if args.command == "down":
        raise SystemExit(command_down(config))
    if args.command == "restart":
        code = command_down(config)
        if code != 0:
            raise SystemExit(code)
        raise SystemExit(command_up(config))
    if args.command == "status":
        print_status(config)
        raise SystemExit(0)
    if args.command == "logs":
        raise SystemExit(print_logs(args.service, config, args.follow))

    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    main()
