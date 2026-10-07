import importlib.machinery
import importlib.util
import os
import sqlite3
import stat
from pathlib import Path

import pytest


HELPER_PATH = Path(__file__).resolve().parents[1] / "scripts/timeclockpi-restore-apply"


@pytest.fixture
def restore_helper(monkeypatch):
    loader = importlib.machinery.SourceFileLoader("restore_apply", str(HELPER_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    helper = importlib.util.module_from_spec(spec)
    loader.exec_module(helper)

    check_private_directory = helper.check_private_directory
    check_status_directory = helper.check_status_directory
    remove_private_child = helper.remove_private_child
    monkeypatch.setattr(
        helper,
        "check_private_directory",
        lambda path: check_private_directory(path, expected_uid=os.getuid()),
    )
    monkeypatch.setattr(
        helper,
        "check_status_directory",
        lambda path: check_status_directory(path, expected_uid=os.getuid()),
    )
    monkeypatch.setattr(
        helper,
        "remove_private_child",
        lambda parent_fd, name: remove_private_child(
            parent_fd, name, expected_uid=os.getuid()
        ),
    )
    monkeypatch.setattr(
        helper,
        "secure_data_directory",
        lambda data_fd: os.fchmod(data_fd, 0o700),
    )
    return helper


def create_database(path, value):
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE record (value TEXT)")
        connection.execute("INSERT INTO record VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def database_value(path):
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT value FROM record").fetchone()[0]
    finally:
        connection.close()


def restore_paths(tmp_path):
    staging = tmp_path / "run/timeclockpi/restore/data"
    data = tmp_path / "var/lib/timeclockpi"
    journal = tmp_path / "var/lib/timeclockpi-restore"
    status = tmp_path / "run/timeclockpi-restore"
    for directory, mode in (
        (staging, 0o755),
        (data, 0o750),
        (journal, 0o700),
        (status, 0o755),
    ):
        directory.mkdir(parents=True)
        directory.chmod(mode)
    return staging, data, journal, status


@pytest.mark.parametrize("filename", ["timeclock.db", "session_key"])
def test_snapshot_rejects_symlinked_staging_files(
    restore_helper, tmp_path, filename
):
    staging, _, _, _ = restore_paths(tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(b"must remain unchanged")
    create_database(staging / "timeclock.db", "valid")
    (staging / "session_key").write_text("normal-key\n", encoding="utf-8")
    (staging / filename).unlink()
    (staging / filename).symlink_to(outside)
    incoming = tmp_path / "incoming"
    incoming.mkdir(mode=0o700)
    incoming_fd = os.open(incoming, os.O_RDONLY | os.O_DIRECTORY)

    try:
        with pytest.raises((OSError, ValueError)):
            restore_helper.snapshot_staging(staging, incoming_fd)
    finally:
        os.close(incoming_fd)

    assert outside.read_bytes() == b"must remain unchanged"


def test_snapshot_rejects_fifo_and_unexpected_paths(restore_helper, tmp_path):
    staging, _, _, _ = restore_paths(tmp_path)
    create_database(staging / "timeclock.db", "valid")
    os.mkfifo(staging / "session_key")
    incoming = tmp_path / "incoming"
    incoming.mkdir(mode=0o700)
    incoming_fd = os.open(incoming, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises((OSError, ValueError)):
            restore_helper.snapshot_staging(staging, incoming_fd)
        (staging / "session_key").unlink()
        (staging / "unexpected").write_text("not allowed", encoding="utf-8")
        with pytest.raises(ValueError, match="unexpected"):
            restore_helper.snapshot_staging(staging, incoming_fd)
    finally:
        os.close(incoming_fd)


def test_replacing_staging_after_snapshot_cannot_redirect_restore(
    restore_helper, tmp_path
):
    staging, data, _, _ = restore_paths(tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(b"must remain unchanged")
    create_database(staging / "timeclock.db", "selected-backup")
    (staging / "session_key").write_text("selected-key\n", encoding="utf-8")
    incoming = tmp_path / "incoming"
    incoming.mkdir(mode=0o700)
    incoming_fd = os.open(incoming, os.O_RDONLY | os.O_DIRECTORY)
    data_fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY)
    try:
        restore_helper.snapshot_staging(staging, incoming_fd)
        (staging / "timeclock.db").unlink()
        (staging / "timeclock.db").symlink_to(outside)
        (staging / "session_key").write_text("attacker-key", encoding="utf-8")
        restore_helper.install_payload(
            incoming_fd, data_fd, (os.getuid(), os.getgid())
        )
    finally:
        os.close(incoming_fd)
        os.close(data_fd)

    assert database_value(data / "timeclock.db") == "selected-backup"
    assert (data / "session_key").read_text(encoding="utf-8") == "selected-key\n"
    assert outside.read_bytes() == b"must remain unchanged"


def test_live_database_symlink_is_rejected_without_touching_target(
    restore_helper, tmp_path
):
    staging, data, journal, status = restore_paths(tmp_path)
    create_database(staging / "timeclock.db", "new")
    create_database(data / "replacement", "outside-data")
    (data / "timeclock.db").symlink_to(data / "replacement")
    commands = []

    with pytest.raises((OSError, ValueError)):
        restore_helper.apply_restore(
            staging,
            data,
            journal,
            status,
            owner=(os.getuid(), os.getgid()),
            command=lambda *args: commands.append(args),
        )

    assert database_value(data / "replacement") == "outside-data"
    assert (data / "timeclock.db").is_symlink()
    assert commands[-1][-2:] == ("start", "timeclockpi.service")


def test_failed_health_check_rolls_back_database_and_session_key(
    restore_helper, tmp_path
):
    staging, data, journal, status = restore_paths(tmp_path)
    create_database(staging / "timeclock.db", "new")
    (staging / "session_key").write_text("new-key\n", encoding="utf-8")
    create_database(data / "timeclock.db", "old")
    (data / "session_key").write_text("old-key\n", encoding="utf-8")
    health_results = iter((False, True))
    commands = []

    with pytest.raises(RuntimeError, match="health check"):
        restore_helper.apply_restore(
            staging,
            data,
            journal,
            status,
            owner=(os.getuid(), os.getgid()),
            command=lambda *args: commands.append(args),
            health_check=lambda command: next(health_results),
        )

    assert database_value(data / "timeclock.db") == "old"
    assert (data / "session_key").read_text(encoding="utf-8") == "old-key\n"
    assert stat.S_IMODE((data / "timeclock.db").stat().st_mode) == 0o644
    assert stat.S_IMODE((data / "session_key").stat().st_mode) == 0o600
    assert (status / "result").read_text(encoding="utf-8").strip() == "rollback"
    assert not (journal / "state").exists()
    assert any(command[-2:] == ("stop", "timeclockpi.service") for command in commands)


def test_systemd_recovery_dependency_is_boot_gated_not_locking_backend_restart():
    root = Path(__file__).resolve().parents[1]
    backend_unit = (root / "deploy/systemd/timeclockpi.service").read_text()
    recovery_unit = (
        root / "deploy/systemd/timeclockpi-restore-recover.service"
    ).read_text()
    startup_unit = (
        root / "deploy/systemd/timeclockpi-startup.service"
    ).read_text()

    assert "Requires=timeclockpi-restore-recover.service" in backend_unit
    assert "After=local-fs.target timeclockpi-restore-recover.service" in backend_unit
    assert (
        "ConditionPathExists=!/run/timeclockpi-restore/boot-recovered"
        in recovery_unit
    )
    assert "Before=timeclockpi-startup.service timeclockpi.service" in recovery_unit
    assert "After=local-fs.target timeclockpi-restore-recover.service" in startup_unit


def test_startup_recovery_restores_durable_pending_rollback(
    restore_helper, tmp_path
):
    _, data, journal, status = restore_paths(tmp_path)
    create_database(data / "timeclock.db", "partial-new")
    (journal / "rollback").mkdir(mode=0o700)
    create_database(journal / "rollback/timeclock.db", "old")
    (journal / "rollback/session_key").write_text("old-key\n", encoding="utf-8")
    (journal / "rollback").chmod(0o700)
    (journal / "state").write_text("pending\n", encoding="utf-8")

    restore_helper.recover_on_startup(
        data,
        journal,
        status,
        owner=(os.getuid(), os.getgid()),
        command=lambda *args: None,
    )

    assert database_value(data / "timeclock.db") == "old"
    assert (data / "session_key").read_text(encoding="utf-8") == "old-key\n"
    assert (status / "result").read_text(encoding="utf-8").strip() == "rollback"
    assert (status / "boot-recovered").read_text(encoding="utf-8").strip() == "complete"
    assert not (journal / "state").exists()


def test_startup_recovery_restores_data_directory_access_without_pending_state(
    restore_helper, tmp_path
):
    _, data, journal, status = restore_paths(tmp_path)
    create_database(data / "timeclock.db", "unchanged")
    data.chmod(0o700)

    restore_helper.recover_on_startup(
        data,
        journal,
        status,
        owner=(os.getuid(), os.getgid()),
        command=lambda *args: None,
    )

    metadata = data.stat()
    assert metadata.st_uid == os.getuid()
    assert metadata.st_gid == os.getgid()
    assert stat.S_IMODE(metadata.st_mode) == 0o750
    assert database_value(data / "timeclock.db") == "unchanged"
    assert (status / "result").read_text(encoding="utf-8").strip() == "idle"
    assert (status / "boot-recovered").read_text(encoding="utf-8").strip() == "complete"
