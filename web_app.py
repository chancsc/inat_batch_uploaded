#!/usr/bin/env python3
from __future__ import annotations

import io
import os
import threading
from datetime import datetime
from pathlib import Path
from shutil import copy2

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

_job: dict = {"status": "idle", "progress": [], "records": [], "error": None}
_lock = threading.Lock()


def _reset():
    with _lock:
        _job.update(status="idle", progress=[], records=[], error=None)


def _log(msg: str) -> None:
    with _lock:
        _job["progress"].append(msg)


def _process(
    photos_dir: str,
    location: str,
    output_dir: str,
    model_path: str,
    cv_threshold: float,
    skip_yolo: bool,
) -> None:
    from crop_photos import batch_crop, get_supported_photos, load_yolo_model
    from exif_utils import get_photo_datetime
    from inat_uploader import get_token
    from location_utils import resolve_location
    from species_utils import get_species_suggestion

    try:
        with _lock:
            _job["status"] = "processing"

        _log(f"Resolving location: {location}")
        lat, lon = resolve_location(location)
        _log(f"Trip location fallback: ({lat:.5f}, {lon:.5f})")

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        if skip_yolo:
            _log("Skipping YOLO — copying full images...")
            photos = get_supported_photos(Path(photos_dir))
            active = []
            for photo in photos:
                dest = out_path / photo.name
                copy2(photo, dest)
                active.append({
                    "source": photo,
                    "cropped": dest,
                    "confidence": None,
                    "class_label": None,
                    "fallback": True,
                })
            _log(f"Copied {len(active)} photo(s)")
        else:
            _log("Loading YOLO model...")
            yolo_model = load_yolo_model(model_path)
            _log("Cropping photos with YOLO...")
            crop_records = batch_crop(Path(photos_dir), out_path, yolo_model, fallback="full")
            active = [r for r in crop_records if r["cropped"] is not None]
            _log(f"Cropped {len(active)} photo(s)")

        for record in active:
            record["datetime"] = get_photo_datetime(record["source"])
            record["lat"] = lat
            record["lon"] = lon

        _log("Authenticating with iNaturalist...")
        token = get_token()

        _log(f"Querying species for {len(active)} photo(s)...")
        for i, record in enumerate(active):
            _log(f"  [{i+1}/{len(active)}] {record['source'].name}")
            try:
                record["species"] = get_species_suggestion(
                    photo_path=record["cropped"],
                    lat=record["lat"],
                    lon=record["lon"],
                    observed_on=record["datetime"].strftime("%Y-%m-%d"),
                    token=token,
                    yolo_class=record.get("class_label"),
                    cv_threshold=cv_threshold,
                )
            except Exception:
                record["species"] = None

        serialized = [_serialize(r) for r in active]
        with _lock:
            _job["records"] = serialized
            _job["status"] = "done"
        _log("Done!")

    except Exception as e:
        import traceback
        with _lock:
            _job["status"] = "error"
            _job["error"] = str(e)
        _log(f"Error: {e}")
        _log(traceback.format_exc())


def _serialize(r: dict) -> dict:
    dt = r.get("datetime")
    return {
        "source": str(r["source"]),
        "cropped": str(r["cropped"]),
        "datetime": dt.isoformat() if dt else None,
        "lat": r["lat"],
        "lon": r["lon"],
        "fallback": r.get("fallback", False),
        "confidence": r.get("confidence"),
        "class_label": r.get("class_label"),
        "species": r.get("species"),
    }


@app.route("/")
def index():
    model_path = os.environ.get("YOLO_MODEL_PATH", "./yolo_butterfly_parts.pt")
    return render_template("index.html", model_path=model_path)


@app.route("/api/process", methods=["POST"])
def api_process():
    data = request.json or {}
    photos_dir  = data.get("photos_dir", "").strip()
    location    = data.get("location", "").strip()
    output_dir  = data.get("output_dir", "./cropped_output").strip()
    model_path  = data.get("model_path", os.environ.get("YOLO_MODEL_PATH", "./yolo_butterfly_parts.pt")).strip()
    cv_threshold = float(data.get("cv_threshold", 0.60))
    skip_yolo   = bool(data.get("skip_yolo", False))

    if not photos_dir or not Path(photos_dir).is_dir():
        return jsonify({"error": f"Directory not found: {photos_dir}"}), 400
    if not location:
        return jsonify({"error": "Location is required"}), 400
    if not skip_yolo and not Path(model_path).exists():
        return jsonify({"error": f"Model not found: {model_path}"}), 400

    _reset()
    threading.Thread(
        target=_process,
        args=(photos_dir, location, output_dir, model_path, cv_threshold, skip_yolo),
        daemon=True,
    ).start()
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    with _lock:
        return jsonify({
            "status": _job["status"],
            "progress": list(_job["progress"]),
            "count": len(_job["records"]),
            "error": _job["error"],
        })


@app.route("/api/records")
def api_records():
    with _lock:
        return jsonify(list(_job["records"]))


@app.route("/api/image")
def api_image():
    path = request.args.get("path", "")
    p = Path(path).resolve()
    if not p.exists() or not p.is_file():
        return "Not found", 404
    suffix = p.suffix.lower()
    mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
    return send_file(str(p), mimetype=mime)


@app.route("/api/recrop", methods=["POST"])
def api_recrop():
    """Apply a manual crop box (image-space pixels) to a record's source photo."""
    from PIL import Image as PILImage
    import piexif

    data = request.json or {}
    idx = int(data["index"])
    x1, y1, x2, y2 = int(data["x1"]), int(data["y1"]), int(data["x2"]), int(data["y2"])

    with _lock:
        records = _job["records"]
    if idx < 0 or idx >= len(records):
        return jsonify({"error": "invalid index"}), 400

    rec = records[idx]
    source = Path(rec["source"])
    dest = Path(rec["cropped"])

    try:
        img = PILImage.open(source).convert("RGB")
        cropped = img.crop((x1, y1, x2, y2))
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=92)
        try:
            exif = piexif.load(str(source))
            dest.write_bytes(buf.getvalue())
            piexif.insert(piexif.dump(exif), str(dest))
        except Exception:
            dest.write_bytes(buf.getvalue())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"ok": True, "cropped": str(dest)})


@app.route("/api/reidentify", methods=["POST"])
def api_reidentify():
    """Re-run iNat CV species identification for the given record indices."""
    from inat_uploader import get_token
    from species_utils import get_species_suggestion

    data = request.json or {}
    indices = data.get("indices", [])
    cv_threshold = float(data.get("cv_threshold", 0.60))

    with _lock:
        records = _job["records"]

    if not records:
        return jsonify({"error": "No records loaded"}), 400

    try:
        token = get_token()
    except Exception as e:
        return jsonify({"error": f"Auth failed: {e}"}), 500

    targets = indices if indices else list(range(len(records)))
    updated = {}
    for i in targets:
        if i < 0 or i >= len(records):
            continue
        rec = records[i]
        try:
            dt_str = rec["datetime"][:10] if rec["datetime"] else datetime.now().strftime("%Y-%m-%d")
            species = get_species_suggestion(
                photo_path=Path(rec["cropped"]),
                lat=rec["lat"],
                lon=rec["lon"],
                observed_on=dt_str,
                token=token,
                cv_threshold=cv_threshold,
            )
        except Exception:
            species = None
        with _lock:
            _job["records"][i]["species"] = species
        updated[i] = species

    return jsonify({"ok": True, "updated": updated})


@app.route("/api/suggest")
def api_suggest():
    """Return top-N iNat CV suggestions for a single record (no auto-apply)."""
    from inat_uploader import get_token
    from species_utils import query_inat_cv

    idx = int(request.args.get("index", 0))
    top_n = int(request.args.get("top_n", 5))

    with _lock:
        records = _job["records"]
    if idx < 0 or idx >= len(records):
        return jsonify({"error": "invalid index"}), 400

    rec = records[idx]
    try:
        token = get_token()
    except Exception as e:
        return jsonify({"error": f"Auth failed: {e}"}), 500

    dt_str = rec["datetime"][:10] if rec["datetime"] else datetime.now().strftime("%Y-%m-%d")
    try:
        suggestions = query_inat_cv(
            photo_path=Path(rec["cropped"]),
            lat=rec["lat"],
            lon=rec["lon"],
            observed_on=dt_str,
            token=token,
            top_n=top_n,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"suggestions": suggestions})


@app.route("/api/set_species", methods=["POST"])
def api_set_species():
    """Manually set (or clear) the species for a record."""
    data = request.json or {}
    idx = int(data["index"])
    species = data.get("species")  # None clears it; dict sets it

    with _lock:
        if 0 <= idx < len(_job["records"]):
            _job["records"][idx]["species"] = species
        else:
            return jsonify({"error": "invalid index"}), 400

    return jsonify({"ok": True})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    from inat_uploader import get_token, upload_observation

    data = request.json or {}
    indices     = data.get("indices", [])
    dry_run     = data.get("dry_run", False)
    tags        = data.get("tags", [])
    description = data.get("description", "")

    with _lock:
        records = list(_job["records"])

    selected = [records[i] for i in indices if 0 <= i < len(records)]
    if not selected:
        return jsonify({"error": "No records selected"}), 400

    try:
        token = get_token()
    except Exception as e:
        return jsonify({"error": f"Auth failed: {e}"}), 500

    results = []
    for rec in selected:
        dt = datetime.fromisoformat(rec["datetime"]) if rec["datetime"] else datetime.now()
        species = rec.get("species")
        taxon_id = species.get("taxon_id") if species else None
        try:
            result = upload_observation(
                cropped_path=Path(rec["cropped"]),
                observed_dt=dt,
                lat=rec["lat"],
                lon=rec["lon"],
                taxon_id=taxon_id,
                access_token=token,
                tags=tags,
                description=description,
                dry_run=dry_run,
            )
            result["source"] = rec["source"]
            result["species"] = species
        except Exception as e:
            result = {"status": "error", "file": rec["source"], "error": str(e), "species": species}
        results.append(result)

    return jsonify(results)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
