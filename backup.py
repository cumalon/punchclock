"""Create and verify portable TimeClockPi backup archives."""

import argparse
import hashlib
import json
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from timeclock import branding
from timeclock.database import DATABASE_PATH, SESSION_KEY_PATH
BACKUP_FORMAT = 1
BRANDING_MANIFEST_VERSION = 1
BRANDING_STATE_FILE = "branding-state"


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_database(path):
    connection = sqlite3.connect(path)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if result != "ok":
        raise ValueError("La base de dades de la còpia no és íntegra")


def create_backup(destination):
    destination = Path(destination).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if not DATABASE_PATH.exists():
        raise ValueError("No s'ha trobat la base de dades")

    now = datetime.now(ZoneInfo("Europe/Madrid"))
    archive_path = destination / f"timeclockpi-backup-{now:%Y%m%d-%H%M%S}.zip"
    partial_path = archive_path.with_suffix(".zip.partial")
    if archive_path.exists():
        raise ValueError("Ja existeix una còpia amb aquest nom")
    if partial_path.exists():
        partial_path.unlink()

    try:
        with tempfile.TemporaryDirectory(prefix="timeclockpi-backup-") as temp:
            database_copy = Path(temp) / "timeclock.db"
            source = sqlite3.connect(DATABASE_PATH)
            target = sqlite3.connect(database_copy)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()

            verify_database(database_copy)
            files = {"data/timeclock.db": database_copy}
            if SESSION_KEY_PATH.exists():
                files["data/session_key"] = SESSION_KEY_PATH
            custom_logo = branding.read_custom_logo()
            if custom_logo is not None:
                logo_copy = Path(temp) / branding.LOGO_FILE_NAME
                logo_copy.write_bytes(custom_logo[0])
                files[branding.BACKUP_LOGO_NAME] = logo_copy

            manifest = {
                "format": BACKUP_FORMAT,
                "created_at": now.isoformat(timespec="seconds"),
                "branding": {
                    "version": BRANDING_MANIFEST_VERSION,
                    "custom_logo": custom_logo is not None,
                },
                "files": {
                    name: {"size": path.stat().st_size, "sha256": sha256_file(path)}
                    for name, path in files.items()
                },
            }

            with zipfile.ZipFile(partial_path, "x", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                )
                for name, path in files.items():
                    archive.write(path, name)

        verify_backup(partial_path)
        partial_path.replace(archive_path)
    except Exception:
        try:
            partial_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return archive_path


def verify_backup(archive_path):
    archive_path = Path(archive_path).expanduser().resolve()
    with zipfile.ZipFile(archive_path, "r") as archive:
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError) as error:
            raise ValueError("Manifest de còpia no vàlid") from error
        if manifest.get("format") != BACKUP_FORMAT:
            raise ValueError("Format de còpia no compatible")

        files = manifest.get("files")
        if not isinstance(files, dict) or "data/timeclock.db" not in files:
            raise ValueError("La còpia no conté la base de dades")

        allowed_names = {"data/timeclock.db", "data/session_key", branding.BACKUP_LOGO_NAME}
        if not set(files) <= allowed_names:
            raise ValueError("La còpia conté fitxers no admesos")

        branding_info = manifest.get("branding")
        has_logo = branding.BACKUP_LOGO_NAME in files
        if branding_info is None:
            if has_logo:
                raise ValueError("La còpia conté un logo sense indicador de personalització")
        elif (
            not isinstance(branding_info, dict)
            or branding_info.get("version") != BRANDING_MANIFEST_VERSION
            or branding_info.get("custom_logo") is not has_logo
        ):
            raise ValueError("Indicador de logo de la còpia no vàlid")

        for name, metadata in files.items():
            try:
                content = archive.read(name)
            except KeyError as error:
                raise ValueError(f"Falta el fitxer {name}") from error
            if len(content) != metadata.get("size"):
                raise ValueError(f"Mida incorrecta per a {name}")
            if hashlib.sha256(content).hexdigest() != metadata.get("sha256"):
                raise ValueError(f"Checksum incorrecte per a {name}")
            if name == branding.BACKUP_LOGO_NAME:
                branding.validate_logo(content)

        with tempfile.TemporaryDirectory(prefix="timeclockpi-verify-") as temp:
            database_copy = Path(temp) / "timeclock.db"
            database_copy.write_bytes(archive.read("data/timeclock.db"))
            verify_database(database_copy)

    return manifest


def restore_backup(archive_path, destination):
    archive_path = Path(archive_path).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()

    manifest = verify_backup(archive_path)

    if destination.exists():
        if not destination.is_dir():
            raise ValueError("El destí de restauració no és un directori")
        if any(destination.iterdir()):
            raise ValueError("El directori de restauració ha d'estar buit")
    else:
        destination.mkdir(parents=True)

    with zipfile.ZipFile(archive_path, "r") as archive:
        for name in manifest["files"]:
            relative_path = Path(name)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ValueError("La còpia conté una ruta no vàlida")
            target = destination / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))

    verify_database(destination / "data" / "timeclock.db")
    if manifest.get("branding") is not None:
        state = "custom" if branding.BACKUP_LOGO_NAME in manifest["files"] else "default"
        (destination / BRANDING_STATE_FILE).write_text(state, encoding="utf-8")
    return destination


def main():
    parser = argparse.ArgumentParser(description="TimeClockPi backup utility")
    commands = parser.add_subparsers(dest="command", required=True)

    create_parser = commands.add_parser("create")
    create_parser.add_argument("destination")

    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("archive")

    restore_parser = commands.add_parser("restore")
    restore_parser.add_argument("archive")
    restore_parser.add_argument("destination")

    args = parser.parse_args()
    try:
        if args.command == "create":
            path = create_backup(args.destination)
            verify_backup(path)
            print(path)
        elif args.command == "verify":
            manifest = verify_backup(args.archive)
            print(f"Còpia correcta: {manifest['created_at']}")
        else:
            destination = restore_backup(args.archive, args.destination)
            print(f"Còpia restaurada a: {destination}")
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
