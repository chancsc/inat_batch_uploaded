from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import pyinaturalist

_token: str | None = None


def get_token() -> str:
    """Return a valid iNaturalist API token.

    Prefers INAT_API_TOKEN (the JWT from inaturalist.org/users/edit → Applications)
    so no OAuth2 app registration is needed.  Falls back to the full OAuth2 flow
    using INAT_APP_ID / INAT_APP_SECRET / INAT_USERNAME / INAT_PASSWORD if the
    direct token is not set.
    """
    global _token
    if _token:
        return _token
    import os
    direct = os.environ.get("INAT_API_TOKEN", "").strip()
    if direct:
        _token = direct
    else:
        _token = pyinaturalist.get_access_token()
    return _token


def resolve_taxon_name(name: str) -> int | None:
    try:
        response = pyinaturalist.get_taxa(q=name, rank=["species", "subspecies"], per_page=1)
        results = response.get("results", [])
        return results[0]["id"] if results else None
    except Exception:
        return None


def upload_observation(
    cropped_path: Path,
    observed_dt: datetime,
    lat: float,
    lon: float,
    taxon_id: int | None,
    access_token: str,
    tags: list[str] | None = None,
    description: str = "",
    dry_run: bool = False,
) -> dict:
    payload = dict(
        observed_on=observed_dt.strftime("%Y-%m-%d"),
        time_observed_at=observed_dt.strftime("%H:%M:%S"),
        latitude=lat,
        longitude=lon,
        positional_accuracy=1000,
        geoprivacy="obscured",
        description=description,
        tag_list=tags or [],
    )
    if taxon_id:
        payload["taxon_id"] = taxon_id

    if dry_run:
        return {"status": "dry_run", "file": cropped_path.name, "payload": payload}

    return _retry_upload(cropped_path, payload, access_token)


def _retry_upload(cropped_path: Path, payload: dict, access_token: str, max_attempts: int = 3) -> dict:
    for attempt in range(max_attempts):
        try:
            response = pyinaturalist.create_observation(
                **payload,
                photos=[str(cropped_path)],
                access_token=access_token,
            )
            obs_id = response[0]["id"]
            url = f"https://www.inaturalist.org/observations/{obs_id}"
            return {"status": "ok", "file": cropped_path.name, "obs_id": obs_id, "url": url}
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (429, 500, 503) and attempt < max_attempts - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
    raise RuntimeError("Upload failed after retries")


def upload_batch(
    records: list[dict],
    access_token: str,
    tags: list[str] | None = None,
    description: str = "",
    dry_run: bool = False,
) -> list[dict]:
    # Species and taxon_id are pre-computed before this call (in upload_observations.py)
    # so each record already carries record["species"] with a taxon_id if found.
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

    results = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
    ) as progress:
        task = progress.add_task("Uploading observations...", total=len(records))
        for record in records:
            cropped_path: Path = record["cropped"]
            observed_dt: datetime = record["datetime"]
            lat: float = record["lat"]
            lon: float = record["lon"]
            species_info: dict | None = record.get("species")
            taxon_id: int | None = species_info.get("taxon_id") if species_info else None

            progress.update(task, description=f"Uploading {cropped_path.name}")
            try:
                result = upload_observation(
                    cropped_path=cropped_path,
                    observed_dt=observed_dt,
                    lat=lat,
                    lon=lon,
                    taxon_id=taxon_id,
                    access_token=access_token,
                    tags=tags,
                    description=description,
                    dry_run=dry_run,
                )
                result["species"] = species_info
            except Exception as e:
                result = {"status": "error", "file": cropped_path.name,
                          "error": str(e), "species": species_info}

            results.append(result)
            progress.advance(task)

    return results
