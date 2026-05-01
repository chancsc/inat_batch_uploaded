from __future__ import annotations

from pathlib import Path

import requests


INAT_CV_URL = "https://api.inaturalist.org/v1/computervision/score_image"


def query_inat_cv(
    photo_path: Path,
    lat: float,
    lon: float,
    observed_on: str,
    token: str,
    top_n: int = 5,
) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    with open(photo_path, "rb") as f:
        files = {"image": (photo_path.name, f, "image/jpeg")}
        data = {"lat": lat, "lng": lon, "observed_on": observed_on}
        response = requests.post(INAT_CV_URL, headers=headers, files=files, data=data, timeout=30)
    response.raise_for_status()
    results = response.json().get("results", [])
    suggestions = []
    for item in results[:top_n]:
        taxon = item.get("taxon", {})
        suggestions.append({
            "taxon_id": taxon.get("id"),
            "name": taxon.get("name", ""),
            "common_name": taxon.get("preferred_common_name", ""),
            "score": round(item.get("combined_score", 0.0), 3),
        })
    return suggestions


def get_species_from_yolo(class_name: str, token: str) -> dict | None:
    import pyinaturalist
    clean_name = class_name.replace("_", " ").strip()
    try:
        response = pyinaturalist.get_taxa(q=clean_name, rank="species", per_page=1)
        results = response.get("results", [])
        if not results:
            return None
        taxon = results[0]
        return {
            "taxon_id": taxon["id"],
            "name": taxon.get("name", ""),
            "common_name": taxon.get("preferred_common_name", ""),
            "score": 1.0,
            "source": "yolo",
        }
    except Exception:
        return None


def get_species_suggestion(
    photo_path: Path,
    lat: float,
    lon: float,
    observed_on: str,
    token: str,
    yolo_class: str | None = None,
    cv_threshold: float = 0.60,
) -> dict | None:
    if yolo_class:
        result = get_species_from_yolo(yolo_class, token)
        if result:
            result["low_confidence"] = False
            return result

    try:
        suggestions = query_inat_cv(photo_path, lat, lon, observed_on, token)
    except Exception:
        return None

    if not suggestions:
        return None

    top = suggestions[0]
    top["source"] = "inat_cv"
    top["low_confidence"] = top["score"] < cv_threshold
    return top
