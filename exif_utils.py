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


def get_exif_tz_offset(image_path: Path) -> str | None:
    exif = _get_raw_exif(image_path)
    if not exif:
        return None
    return exif.get("OffsetTimeOriginal") or exif.get("OffsetTime") or None


def get_photo_datetime(image_path: Path) -> tuple[datetime, bool]:
    """Return (datetime, has_time). has_time is False when only the date is known (no EXIF time)."""
    dt = get_exif_datetime(image_path)
    if dt:
        return dt, True
    mtime = os.path.getmtime(image_path)
    return datetime.fromtimestamp(mtime), False


def get_exif_gps(image_path: Path) -> tuple[float, float] | None:
    exif = _get_raw_exif(image_path)
    if not exif:
        return None
    gps = exif.get("GPSInfo")
    if not gps:
        return None
    try:
        def _rat(v) -> float:
            # IFDRational, plain float, or (num, denom) tuple
            if hasattr(v, "numerator"):
                return float(v.numerator) / float(v.denominator)
            if isinstance(v, tuple):
                return v[0] / v[1]
            return float(v)

        def _dms(tup, ref: str) -> float:
            d, m, s = (_rat(x) for x in tup)
            deg = d + m / 60 + s / 3600
            return -deg if ref in ("S", "W") else deg

        lat = _dms(gps[2], gps[1])
        lon = _dms(gps[4], gps[3])
        return lat, lon
    except Exception:
        return None
