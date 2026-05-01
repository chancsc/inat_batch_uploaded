from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PIL import Image, ExifTags


def _get_raw_exif(image_path: Path) -> dict | None:
    try:
        img = Image.open(image_path)
        raw = img._getexif()
        if not raw:
            return None
        return {ExifTags.TAGS.get(k, k): v for k, v in raw.items()}
    except Exception:
        return None


def get_exif_datetime(image_path: Path) -> datetime | None:
    exif = _get_raw_exif(image_path)
    if not exif:
        return None
    for tag in ("DateTimeOriginal", "DateTime"):
        value = exif.get(tag)
        if value:
            try:
                return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
            except ValueError:
                continue
    return None


def get_photo_datetime(image_path: Path) -> datetime:
    dt = get_exif_datetime(image_path)
    if dt:
        return dt
    mtime = os.path.getmtime(image_path)
    return datetime.fromtimestamp(mtime)
