from __future__ import annotations

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable


_geocoder = Nominatim(user_agent="inat_batch_uploader/1.0")


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
    for attempt in range(2):
        try:
            location = _geocoder.geocode(place_name, exactly_one=True, timeout=10)
            if location is None:
                raise ValueError(f"Place not found: {place_name!r}")
            return location.latitude, location.longitude
        except (GeocoderTimedOut, GeocoderUnavailable):
            if attempt == 1:
                raise ValueError(f"Geocoding service unavailable for: {place_name!r}")
    raise ValueError(f"Could not geocode: {place_name!r}")


def resolve_location(user_input: str) -> tuple[float, float]:
    coords = parse_coordinates(user_input)
    if coords is not None:
        return coords
    return geocode_place(user_input)
