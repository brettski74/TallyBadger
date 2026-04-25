from pathlib import Path
from types import SimpleNamespace

from tallybadger import tbad


def test_read_pid_handles_missing_and_invalid(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pid"
    assert tbad.read_pid(missing) is None

    invalid = tmp_path / "invalid.pid"
    invalid.write_text("not-a-pid", encoding="utf-8")
    assert tbad.read_pid(invalid) is None


def test_read_pid_returns_integer(tmp_path: Path) -> None:
    pid_file = tmp_path / "api.pid"
    pid_file.write_text("4242", encoding="utf-8")
    assert tbad.read_pid(pid_file) == 4242


def test_load_config_honors_environment(monkeypatch) -> None:
    monkeypatch.setenv("TBAD_API_CMD", "custom-api")
    monkeypatch.setenv("TBAD_FRONTEND_CMD", "custom-frontend")
    monkeypatch.setenv("TBAD_RUN_DIR", "tmp/run")
    monkeypatch.setenv("TBAD_LOG_DIR", "tmp/logs")

    config = tbad.load_config()

    assert config.api_cmd == "custom-api"
    assert config.frontend_cmd == "custom-frontend"
    assert str(config.run_dir) == "tmp/run"
    assert str(config.log_dir) == "tmp/logs"


def test_ensure_running_starts_process_and_writes_pid(
    tmp_path: Path, monkeypatch
) -> None:
    config = tbad.TbadConfig(
        run_dir=tmp_path / "run",
        log_dir=tmp_path / "logs",
        api_cmd="api",
        frontend_cmd="frontend",
        db_up_cmd="db-up",
        db_down_cmd="db-down",
        db_status_cmd="db-status",
        db_logs_cmd="db-logs",
    )
    fake_process = SimpleNamespace(pid=4242)
    monkeypatch.setattr(tbad.subprocess, "Popen", lambda *args, **kwargs: fake_process)

    tbad.ensure_running("api", "echo hello", config)

    assert (config.run_dir / "api.pid").read_text(encoding="utf-8") == "4242"
    assert (config.log_dir / "api.log").exists()


def test_ensure_running_is_idempotent_when_pid_is_alive(
    tmp_path: Path, monkeypatch
) -> None:
    config = tbad.TbadConfig(
        run_dir=tmp_path / "run",
        log_dir=tmp_path / "logs",
        api_cmd="api",
        frontend_cmd="frontend",
        db_up_cmd="db-up",
        db_down_cmd="db-down",
        db_status_cmd="db-status",
        db_logs_cmd="db-logs",
    )
    config.run_dir.mkdir(parents=True, exist_ok=True)
    (config.run_dir / "api.pid").write_text("7777", encoding="utf-8")
    monkeypatch.setattr(tbad, "is_pid_running", lambda pid: pid == 7777)

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("Popen should not be called for already-running service")

    monkeypatch.setattr(tbad.subprocess, "Popen", should_not_run)
    tbad.ensure_running("api", "echo hello", config)


def test_stop_service_cleans_stale_pid_file(tmp_path: Path, monkeypatch) -> None:
    config = tbad.TbadConfig(
        run_dir=tmp_path / "run",
        log_dir=tmp_path / "logs",
        api_cmd="api",
        frontend_cmd="frontend",
        db_up_cmd="db-up",
        db_down_cmd="db-down",
        db_status_cmd="db-status",
        db_logs_cmd="db-logs",
    )
    config.run_dir.mkdir(parents=True, exist_ok=True)
    pid_path = config.run_dir / "api.pid"
    pid_path.write_text("1234", encoding="utf-8")
    monkeypatch.setattr(tbad, "is_pid_running", lambda _pid: False)

    tbad.stop_service("api", config)

    assert not pid_path.exists()


def test_command_up_starts_db_then_services(tmp_path: Path, monkeypatch) -> None:
    config = tbad.TbadConfig(
        run_dir=tmp_path / "run",
        log_dir=tmp_path / "logs",
        api_cmd="api-cmd",
        frontend_cmd="frontend-cmd",
        db_up_cmd="db-up",
        db_down_cmd="db-down",
        db_status_cmd="db-status",
        db_logs_cmd="db-logs",
    )
    starts: list[tuple[str, str]] = []

    monkeypatch.setattr(
        tbad,
        "run_command",
        lambda _cmd: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        tbad,
        "ensure_running",
        lambda service, command, _cfg: starts.append((service, command)),
    )

    assert tbad.command_up(config) == 0
    assert starts == [("api", "api-cmd"), ("frontend", "frontend-cmd")]


def test_command_up_returns_error_when_db_start_fails(tmp_path: Path, monkeypatch) -> None:
    config = tbad.TbadConfig(
        run_dir=tmp_path / "run",
        log_dir=tmp_path / "logs",
        api_cmd="api-cmd",
        frontend_cmd="frontend-cmd",
        db_up_cmd="db-up",
        db_down_cmd="db-down",
        db_status_cmd="db-status",
        db_logs_cmd="db-logs",
    )

    monkeypatch.setattr(
        tbad,
        "run_command",
        lambda _cmd: SimpleNamespace(returncode=9, stdout="", stderr="boom"),
    )

    assert tbad.command_up(config) == 9
