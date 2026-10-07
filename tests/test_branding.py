import io
import struct
import zlib
import zipfile

import pytest

import backup
import timeclock.database as database
from timeclock import branding


def make_png(width=4, height=4, extra=b""):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        branding.PNG_SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + extra
        + chunk(b"IEND", b"")
    )


def make_jpeg(width=8, height=8):
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xe0\x00\x02" + sof + b"\xff\xda\x00\x02\x00\xff\xd9"


def upload(client, data, filename="logo.png", mime="image/png"):
    return client.post(
        "/api/admin/logo",
        data={"logo": (io.BytesIO(data), filename, mime)},
        content_type="multipart/form-data",
    )


def test_default_logo_is_generic_repository_asset(client):
    response = client.get("/branding/logo")
    assert response.status_code == 200
    assert response.mimetype == "image/svg+xml"
    assert b"TimeClockPi" in response.data
    assert b"AFA" not in response.data


def test_admin_uploads_replaces_and_removes_logo(admin_client):
    assert admin_client.get("/api/admin/logo").get_json()["custom"] is False
    png = make_png()
    assert upload(admin_client, png).status_code == 200
    response = admin_client.get("/branding/logo")
    assert response.mimetype == "image/png" and response.data == png
    assert admin_client.get("/api/admin/logo").get_json()["custom"] is True

    jpeg = make_jpeg()
    assert upload(admin_client, jpeg, "a.jpg", "image/jpeg").status_code == 200
    response = admin_client.get("/branding/logo")
    assert response.mimetype == "image/jpeg" and response.data == jpeg

    assert admin_client.delete("/api/admin/logo").status_code == 200
    assert admin_client.get("/branding/logo").mimetype == "image/svg+xml"
    assert admin_client.get("/api/admin/logo").get_json()["custom"] is False


def test_unauthenticated_modification_is_rejected(client):
    assert upload(client, make_png()).status_code == 401
    assert client.delete("/api/admin/logo").status_code == 401
    assert not branding.logo_path().exists()


def test_csrf_is_required(admin_client):
    headers = {"X-CSRF-Token": "wrong"}
    response = admin_client.post(
        "/api/admin/logo",
        data={"logo": (io.BytesIO(make_png()), "l.png")},
        content_type="multipart/form-data",
        headers=headers,
    )
    assert response.status_code == 403


@pytest.mark.parametrize("data", [
    b"not an image",
    b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
    b"GIF89a" + b"\x00" * 20,
    branding.PNG_SIGNATURE + b"garbage",
    b"\xff\xd8\xff\xe0garbage",
    b"",
])
def test_invalid_images_are_rejected(admin_client, data):
    assert upload(admin_client, data).status_code == 400
    assert not branding.logo_path().exists()


def test_oversized_images_are_rejected(admin_client):
    slightly_big = make_png(extra=b"\x00" * (branding.MAX_LOGO_BYTES + 10))
    assert upload(admin_client, slightly_big).status_code == 400
    big = make_png(extra=b"\x00" * (branding.MAX_LOGO_BYTES + 100 * 1024))
    assert upload(admin_client, big).status_code == 413
    assert not branding.logo_path().exists()


def test_huge_dimensions_are_rejected(admin_client):
    assert upload(admin_client, make_png(branding.MAX_LOGO_DIMENSION + 1, 1)).status_code == 400


def test_filename_cannot_affect_destination(admin_client, tmp_path):
    response = upload(admin_client, make_png(), "../../evil.png")
    assert response.status_code == 200
    assert sorted(p.name for p in branding.logo_directory().iterdir()) == ["custom-logo"]
    assert not (tmp_path / "evil.png").exists()
    assert not (tmp_path.parent / "evil.png").exists()


def test_invalid_replacement_preserves_previous_logo(admin_client):
    png = make_png()
    upload(admin_client, png)
    assert upload(admin_client, b"broken").status_code == 400
    assert branding.logo_path().read_bytes() == png


def test_symlinked_logo_is_not_followed_or_overwritten(admin_client, tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("keep")
    branding.logo_directory().mkdir(parents=True)
    branding.logo_path().symlink_to(victim)
    assert admin_client.get("/branding/logo").mimetype == "image/svg+xml"
    assert upload(admin_client, make_png()).status_code == 200
    assert victim.read_text() == "keep"
    assert not branding.logo_path().is_symlink()


def test_remove_only_removes_expected_file(admin_client):
    upload(admin_client, make_png())
    other = branding.logo_directory() / "other"
    other.write_text("x")
    admin_client.delete("/api/admin/logo")
    assert other.exists() and not branding.logo_path().exists()


@pytest.fixture
def backup_env(tmp_path, monkeypatch):
    db = tmp_path / "live.db"
    database.DATABASE_PATH = db
    monkeypatch.setattr(database, "DATABASE_PATH", db)
    monkeypatch.setattr(backup, "DATABASE_PATH", db)
    monkeypatch.setattr(backup, "SESSION_KEY_PATH", tmp_path / "missing-key")
    database.init_database()
    return tmp_path


def test_backup_without_logo_is_valid_and_restorable(backup_env):
    archive = backup.create_backup(backup_env / "out")
    manifest = backup.verify_backup(archive)
    assert branding.BACKUP_LOGO_NAME not in manifest["files"]
    restored = backup.restore_backup(archive, backup_env / "restored")
    assert not (restored / "branding").exists()


def test_backup_with_logo_restores_it(backup_env):
    png = make_png()
    branding.save_custom_logo(png)
    archive = backup.create_backup(backup_env / "out")
    assert branding.BACKUP_LOGO_NAME in backup.verify_backup(archive)["files"]
    restored = backup.restore_backup(archive, backup_env / "restored")
    assert (restored / branding.BACKUP_LOGO_NAME).read_bytes() == png


def test_backup_with_invalid_logo_is_rejected(backup_env):
    archive = backup.create_backup(backup_env / "out")
    import hashlib, json
    bad = backup_env / "bad.zip"
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(bad, "w") as dst:
        manifest = json.loads(src.read("manifest.json"))
        content = b"<svg onload=alert(1)>"
        manifest["files"][branding.BACKUP_LOGO_NAME] = {
            "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        dst.writestr("manifest.json", json.dumps(manifest))
        for name in src.namelist():
            if name != "manifest.json":
                dst.writestr(name, src.read(name))
        dst.writestr(branding.BACKUP_LOGO_NAME, content)
    with pytest.raises(ValueError):
        backup.verify_backup(bad)


# --- transactional logo restore ---------------------------------------------

import json
import os
import shutil
import time

import app as app_module


def make_legacy(archive, target):
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(target, "w") as dst:
        manifest = json.loads(src.read("manifest.json"))
        manifest.pop("branding")
        manifest["files"].pop(branding.BACKUP_LOGO_NAME, None)
        dst.writestr("manifest.json", json.dumps(manifest))
        for name in manifest["files"]:
            dst.writestr(name, src.read(name))
    return target


@pytest.fixture
def restore_env(admin_client, tmp_path, monkeypatch):
    usb = tmp_path / "usb"
    usb.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    status = tmp_path / "status"
    monkeypatch.setattr(app_module, "USB_MOUNTPOINT", usb)
    monkeypatch.setattr(app_module, "USB_RESTORE_DIR", run_dir / "restore")
    monkeypatch.setattr(app_module, "USB_RESTORE_STATUS", status)
    monkeypatch.setattr(app_module, "get_usb_status", lambda: {"state": "available"})
    monkeypatch.setattr(backup, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(backup, "SESSION_KEY_PATH", tmp_path / "missing-key")
    monkeypatch.setattr(app_module, "subprocess", type("S", (), {
        "run": staticmethod(lambda *a, **k: None)}))

    def restore(archive):
        name = archive.name
        if archive.parent != usb:
            archive.replace(usb / name)
        r = admin_client.post("/api/admin/usb/authorize-restore", json={"filename": name})
        assert r.status_code == 200, r.get_json()
        r = admin_client.post("/api/admin/usb/prepare-restore",
                              json={"authorization_token": r.get_json()["authorization_token"]})
        assert r.status_code == 200, r.get_json()
        r = admin_client.post("/api/admin/usb/apply-restore", json={
            "apply_token": r.get_json()["apply_token"], "confirmation": "RESTAURAR"})
        assert r.status_code == 202

    def helper_finishes(state):
        if state == "success":
            shutil.copyfile(run_dir / "restore" / "data" / "timeclock.db", database.DATABASE_PATH)
        status.write_text(state + "\n")
        later = time.time_ns() + 10_000_000
        os.utime(status, ns=(later, later))

    return admin_client, tmp_path, usb, restore, helper_finishes, status


def logo_kind(client):
    return client.get("/branding/logo").mimetype


def test_restore_with_logo_applies_only_after_success(restore_env):
    client, tmp_path, usb, restore, finish, status = restore_env
    png = make_png(6, 6)
    branding.save_custom_logo(png)
    archive = backup.create_backup(tmp_path / "out")
    branding.remove_custom_logo()
    old = make_jpeg()
    branding.save_custom_logo(old)
    restore(archive)
    assert client.get("/branding/logo").data == old
    finish("running")
    assert client.get("/branding/logo").data == old
    finish("success")
    assert client.get("/api/admin/usb/restore-status").get_json()["state"] == "success"
    assert client.get("/branding/logo").data == png


def test_rolled_back_restore_keeps_previous_logo(restore_env):
    client, tmp_path, usb, restore, finish, status = restore_env
    branding.save_custom_logo(make_png(6, 6))
    archive = backup.create_backup(tmp_path / "out")
    old = make_jpeg()
    branding.save_custom_logo(old)
    restore(archive)
    finish("rollback")
    assert client.get("/branding/logo").data == old
    assert not app_module.pending_branding_dir().exists()
    finish("success")  # a later unrelated success must not apply the discarded logo
    assert client.get("/branding/logo").data == old


def test_new_backup_without_logo_removes_current_logo(restore_env):
    client, tmp_path, usb, restore, finish, status = restore_env
    archive = backup.create_backup(tmp_path / "out")
    branding.save_custom_logo(make_png())
    restore(archive)
    assert logo_kind(client) == "image/png"
    finish("success")
    assert logo_kind(client) == "image/svg+xml"
    assert not branding.logo_path().exists()


def test_legacy_backup_preserves_current_logo(restore_env):
    client, tmp_path, usb, restore, finish, status = restore_env
    archive = backup.create_backup(tmp_path / "out")
    legacy = make_legacy(archive, tmp_path / "timeclockpi-backup-20200101-000000.zip")
    png = make_png()
    branding.save_custom_logo(png)
    restore(legacy)
    finish("success")
    assert client.get("/branding/logo").data == png


def test_manifest_branding_marker_must_match_contents(backup_env):
    archive = backup.create_backup(backup_env / "out")
    bad = backup_env / "bad2.zip"
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(bad, "w") as dst:
        manifest = json.loads(src.read("manifest.json"))
        manifest["branding"]["custom_logo"] = True
        dst.writestr("manifest.json", json.dumps(manifest))
        for name in manifest["files"]:
            dst.writestr(name, src.read(name))
    with pytest.raises(ValueError):
        backup.verify_backup(bad)


def test_success_survives_power_loss_before_any_http_request(restore_env, tmp_path):
    client, tmp_path, usb, restore, finish, status = restore_env
    png = make_png(6, 6)
    branding.save_custom_logo(png)
    archive = backup.create_backup(tmp_path / "out")
    branding.save_custom_logo(make_jpeg())
    restore(archive)
    finish("success")
    # power is lost: all of /run disappears before the app notices the success
    shutil.rmtree(app_module.USB_RESTORE_DIR)
    status.unlink()
    assert branding.logo_path().read_bytes() != png

    app_module.finalize_pending_branding(startup=True)

    assert branding.logo_path().read_bytes() == png
    assert not app_module.pending_branding_dir().exists()
    assert not app_module.live_database_has_nonce("x")


def test_rollback_followed_by_reboot_keeps_previous_logo(restore_env):
    client, tmp_path, usb, restore, finish, status = restore_env
    branding.save_custom_logo(make_png(6, 6))
    archive = backup.create_backup(tmp_path / "out")
    old = make_jpeg()
    branding.save_custom_logo(old)
    restore(archive)
    shutil.rmtree(app_module.USB_RESTORE_DIR)  # reboot before any request
    app_module.finalize_pending_branding(startup=True)
    assert branding.logo_path().read_bytes() == old
    assert not app_module.pending_branding_dir().exists()


def test_power_loss_after_logo_applied_before_cleanup_is_idempotent(restore_env):
    client, tmp_path, usb, restore, finish, status = restore_env
    archive = backup.create_backup(tmp_path / "out")
    branding.save_custom_logo(make_png())
    restore(archive)
    finish("success")
    app_module.finalize_pending_branding(startup=True)
    app_module.finalize_pending_branding(startup=True)
    assert not branding.logo_path().exists()


def test_logo_mutations_fsync_the_branding_directory(monkeypatch):
    synced = []
    real = branding.fsync_directory
    monkeypatch.setattr(branding, "fsync_directory", lambda path: (synced.append(path), real(path)))
    branding.save_custom_logo(make_png())
    assert branding.logo_directory() in synced
    synced.clear()
    branding.remove_custom_logo()
    assert synced == [branding.logo_directory()]
    synced.clear()
    branding.remove_custom_logo()  # nothing to remove: idempotent, no sync needed
    assert synced == [] and not branding.logo_path().exists()


def test_failed_directory_sync_is_reported_so_restore_is_not_consumed(monkeypatch):
    def fail(path):
        raise OSError("sync failed")
    monkeypatch.setattr(branding, "fsync_directory", fail)
    with pytest.raises(OSError):
        branding.save_custom_logo(make_png())


def test_failed_health_check_after_service_start_keeps_previous_logo(restore_env):
    client, tmp_path, usb, restore, finish, status = restore_env
    branding.save_custom_logo(make_png(6, 6))
    archive = backup.create_backup(tmp_path / "out")
    old = make_jpeg()
    branding.save_custom_logo(old)
    live_before = tmp_path / "live-before.db"
    shutil.copyfile(database.DATABASE_PATH, live_before)
    restore(archive)

    # helper: status "running", staged database installed, service (re)started
    finish("running")
    shutil.copyfile(app_module.USB_RESTORE_DIR / "data" / "timeclock.db", database.DATABASE_PATH)
    app_module.finalize_pending_branding(startup=True)
    assert client.get("/branding/logo").data == old
    assert app_module.pending_branding_dir().exists()

    # health check fails: helper restores the previous database and reports rollback
    shutil.copyfile(live_before, database.DATABASE_PATH)
    finish("rollback")
    app_module.finalize_pending_branding(startup=True)
    assert client.get("/branding/logo").data == old
    assert not app_module.pending_branding_dir().exists()


def test_rollback_with_service_restart_and_reboot_keeps_previous_logo(restore_env):
    client, tmp_path, usb, restore, finish, status = restore_env
    branding.save_custom_logo(make_png(6, 6))
    archive = backup.create_backup(tmp_path / "out")
    old = make_jpeg()
    branding.save_custom_logo(old)
    live_before = tmp_path / "live-before.db"
    shutil.copyfile(database.DATABASE_PATH, live_before)
    restore(archive)
    finish("running")
    shutil.copyfile(app_module.USB_RESTORE_DIR / "data" / "timeclock.db", database.DATABASE_PATH)
    # power loss during the health check; boot recovery rolls back, status idle/rollback
    shutil.copyfile(live_before, database.DATABASE_PATH)
    shutil.rmtree(app_module.USB_RESTORE_DIR)
    finish("rollback")
    app_module.finalize_pending_branding(startup=True)
    assert client.get("/branding/logo").data == old


def test_boot_after_committed_restore_applies_logo_when_status_is_idle(restore_env):
    client, tmp_path, usb, restore, finish, status = restore_env
    png = make_png(6, 6)
    branding.save_custom_logo(png)
    archive = backup.create_backup(tmp_path / "out")
    branding.save_custom_logo(make_jpeg())
    restore(archive)
    finish("success")
    shutil.rmtree(app_module.USB_RESTORE_DIR)
    status.write_text("idle\n")  # boot recovery found no journal state left
    app_module.finalize_pending_branding(startup=True)
    assert branding.logo_path().read_bytes() == png
