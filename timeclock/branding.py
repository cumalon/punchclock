"""Installation-local custom logo stored under the data directory."""

import os
import stat
import struct
import tempfile
from pathlib import Path

from timeclock import database

LOGO_DIR_NAME = "branding"
LOGO_FILE_NAME = "custom-logo"
BACKUP_LOGO_NAME = f"{LOGO_DIR_NAME}/{LOGO_FILE_NAME}"
MAX_LOGO_BYTES = 1024 * 1024
MAX_LOGO_DIMENSION = 4096
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


LOGO_ERROR_MESSAGES = {
    "png_invalid": "Imatge PNG no vàlida",
    "png_incomplete": "Imatge PNG incompleta",
    "jpeg_invalid": "Imatge JPEG no vàlida",
    "jpeg_incomplete": "Imatge JPEG incompleta",
    "empty": "El fitxer està buit",
    "too_large": "El logo supera la mida màxima permesa (1 MB)",
    "format": "Format no admès. Només s'accepten imatges PNG o JPEG",
    "dimensions": "Les dimensions del logo no són vàlides",
    "directory": "El directori del logo no és vàlid",
}


class LogoError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code

    @property
    def message(self):
        return LOGO_ERROR_MESSAGES.get(self.code, "Logo no vàlid")


def logo_directory():
    return Path(database.DATA_DIR) / LOGO_DIR_NAME


def logo_path():
    return logo_directory() / LOGO_FILE_NAME


def _png_dimensions(data):
    if len(data) < 33 or data[12:16] != b"IHDR" or struct.unpack(">I", data[8:12])[0] != 13:
        raise LogoError("png_invalid")
    if data[-12:] != b"\x00\x00\x00\x00IEND\xaeB`\x82":
        raise LogoError("png_incomplete")
    return struct.unpack(">II", data[16:24])


def _jpeg_dimensions(data):
    if data[-2:] != b"\xff\xd9":
        raise LogoError("jpeg_incomplete")
    position = 2
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            raise LogoError("jpeg_invalid")
        marker = data[position + 1]
        if marker == 0xFF:
            position += 1
            continue
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            position += 2
            continue
        if marker == 0xD9 or marker == 0xDA:
            break
        length = struct.unpack(">H", data[position + 2:position + 4])[0]
        if length < 2 or position + 2 + length > len(data):
            raise LogoError("jpeg_invalid")
        if marker in JPEG_SOF_MARKERS:
            if length < 8:
                raise LogoError("jpeg_invalid")
            height, width = struct.unpack(">HH", data[position + 5:position + 9])
            return width, height
        position += 2 + length
    raise LogoError("jpeg_invalid")


def validate_logo(data):
    """Return the MIME type of a supported image ."""
    if not data:
        raise LogoError("empty")
    if len(data) > MAX_LOGO_BYTES:
        raise LogoError("too_large")
    if data.startswith(PNG_SIGNATURE):
        mime, (width, height) = "image/png", _png_dimensions(data)
    elif data.startswith(b"\xff\xd8\xff"):
        mime, (width, height) = "image/jpeg", _jpeg_dimensions(data)
    else:
        raise LogoError("format")
    if not 0 < width <= MAX_LOGO_DIMENSION or not 0 < height <= MAX_LOGO_DIMENSION:
        raise LogoError("dimensions")
    return mime


def read_custom_logo():
    """Return (bytes, mime) of the valid custom logo, or None."""
    directory = logo_directory()
    try:
        if directory.is_symlink() or not directory.is_dir():
            return None
        fd = os.open(directory / LOGO_FILE_NAME, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return None
            data = handle.read(MAX_LOGO_BYTES + 1)
    except OSError:
        return None
    try:
        return data, validate_logo(data)
    except ValueError:
        return None


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_custom_logo(data):
    """Validate and atomically install the custom logo."""
    mime = validate_logo(data)
    directory = logo_directory()
    if directory.is_symlink():
        raise LogoError("directory")
    created = not directory.exists()
    directory.mkdir(parents=True, exist_ok=True, mode=0o750)
    if created:
        fsync_directory(directory.parent)
    target = directory / LOGO_FILE_NAME
    if target.is_symlink():
        target.unlink()
    fd, temp_name = tempfile.mkstemp(prefix=".logo-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o640)
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    fsync_directory(directory)
    return mime


def remove_custom_logo():
    target = logo_path()
    try:
        if target.is_symlink() or target.is_file():
            target.unlink()
        else:
            return
    except FileNotFoundError:
        return
    fsync_directory(target.parent)


def has_custom_logo():
    return read_custom_logo() is not None
