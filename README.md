# iNat Batch Uploader

Batch-upload butterfly photos to [iNaturalist](https://www.inaturalist.org) with automatic YOLO-based cropping and iNat computer vision species identification. Review and approve observations through a browser-based web UI before anything is submitted.

---

## Features

- **YOLO detection & crop** — detects butterfly in each photo and crops tightly around it (30% padding), or skip detection and use full images
- **iNat CV species ID** — queries the iNaturalist computer vision API and shows top-5 suggestions with confidence scores
- **Web UI** — accessible over local network or Cloudflare tunnel; process, preview, identify, and upload from any device including mobile
- **Upload from browser** — file picker or drag-and-drop to send photos from your device directly to the server; no manual file transfer needed
- **Manual crop tool** — draw a square selection on the original photo, then drag the 8 corner/edge handles to fine-tune; drag inside to reposition
- **Per-photo species selector** — choose from top-5 CV suggestions, pick "Butterflies (general)" (Papilionoidea) as a fallback, or leave as no ID
- **Re-identify** — re-run iNat CV on all photos or a single photo (e.g. after re-cropping)
- **Geoprivacy** — all observations uploaded with `obscured` geoprivacy; iNat handles public pin masking while storing the exact private coordinates
- **Delete after upload** — optional checkbox to remove source photos from the device after successful upload
- **Token hot-reload** — update `INAT_API_TOKEN` in `.env` and it takes effect immediately without restarting the server

---

## Requirements

- Python 3.10+
- A YOLO butterfly model file (`.pt`)
- An iNaturalist account with an API token

---

## Setup

```bash
git clone https://github.com/chancsc/inat_batch_uploaded.git
cd inat_batch_uploaded
bash setup.sh
```

Copy and edit the environment file:

```bash
cp .env.example .env   # or edit .env directly
```

Set your iNaturalist API token in `.env`:

```
INAT_API_TOKEN="eyJ..."   # from inaturalist.org → Account Settings → Applications
YOLO_MODEL_PATH=./yolo_butterfly_parts.pt
```

Get your API token at **inaturalist.org → Account Settings → scroll to Applications → click "Get token"**. Tokens expire periodically; paste a fresh one into `.env` — no restart needed.

---

## Usage

### Web UI (recommended)

```bash
bash run_web.sh
```

This starts Flask on port 5000 and opens a Cloudflare tunnel. The public URL is printed to the terminal — open it on any device.

**Workflow:**

1. Enter the photos directory path on the server, or upload photos directly from your device
2. Enter the trip location (place name or `lat,lon`)
3. Click **Process Photos** — YOLO crops and iNat CV identification run in the background with a live log
4. Review the photo grid — click a card to toggle selection
5. Use **✂ Crop** to manually adjust the crop area; **🔍 ID** to pick from CV suggestions
6. Optionally tick **Delete source photos after successful upload**
7. Click **Upload selected** or **Dry run** to preview without submitting

Local network access (same Wi-Fi):

```
http://192.168.1.237:5000
```

### CLI (terminal UI)

```bash
bash run.sh ~/storage/pictures
bash run.sh ~/storage/pictures --dry-run
```

---

## Project structure

```
web_app.py          Flask app and API endpoints
upload_observations.py  CLI entry point
crop_photos.py      YOLO detection and cropping
species_utils.py    iNat CV API wrapper
inat_uploader.py    iNat observation upload + auth
exif_utils.py       EXIF datetime and GPS extraction
location_utils.py   Place name → coordinates
preview_ui.py       Textual TUI (CLI mode)
templates/
  index.html        Web UI (single-page)
run_web.sh          Start Flask + Cloudflare tunnel
run.sh              Start CLI tool
setup.sh            Create venv and install dependencies
```

---

## Notes

- Observations are uploaded with `geoprivacy: obscured` — the exact GPS coordinates are stored privately on iNaturalist while the public map pin is shifted automatically
- The iNat CV endpoint is read-only and does not create observations; it is the same engine used on the iNaturalist website
- During dry run, species identification still runs so you can preview results before committing
