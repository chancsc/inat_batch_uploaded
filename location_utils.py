from __future__ import annotations

import json
from pathlib import Path

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable


_geocoder = Nominatim(user_agent="inat_batch_uploader/1.0")
_CACHE_FILE = Path(__file__).parent / ".location_cache.json"


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_FILE.read_text()) if _CACHE_FILE.exists() else {}
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
    except Exception:
        pass


def list_cached() -> list[dict]:
    """Return all cached locations as [{name, lat, lon}] sorted by name."""
    cache = _load_cache()
    return sorted(cache.values(), key=lambda e: e["name"].lower())


def parse_coordinates(text: str) -> tuple[float, float] | None:
    parts = text.strip().split(",")
    if len(parts) == 2:
        try:
            lat = float(parts[0].strip())
            lon = float(parts[1].strip())
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
        except ValueError:
            pass
    return None


def geocode_place(place_name: str) -> tuple[float, float]:
    cache = _load_cache()
    key = place_name.strip().lower()
    if key in cache:
        entry = cache[key]
        return entry["lat"], entry["lon"]

    for attempt in range(2):
        try:
            location = _geocoder.geocode(place_name, exactly_one=True, timeout=10)
            if location is None:
                raise ValueError(f"Place not found: {place_name!r}")
            lat, lon = location.latitude, location.longitude
            cache[key] = {"name": place_name.strip(), "lat": lat, "lon": lon}
            _save_cache(cache)
            return lat, lon
        except (GeocoderTimedOut, GeocoderUnavailable):
            if attempt == 1:
                raise ValueError(f"Geocoding service unavailable for: {place_name!r}")
    raise ValueError(f"Could not geocode: {place_name!r}")


def resolve_location(user_input: str) -> tuple[float, float]:
    coords = parse_coordinates(user_input)
    if coords is not None:
        return coords
    return geocode_place(user_input)
