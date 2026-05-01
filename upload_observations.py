#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from crop_photos import batch_crop, load_yolo_model
from exif_utils import get_photo_datetime
from inat_uploader import get_token, upload_batch, resolve_taxon_name
from location_utils import resolve_location
from preview_ui import run_preview
from species_utils import get_species_suggestion

console = Console()


def _prompt_location() -> tuple[float, float]:
    for attempt in range(3):
        raw = click.prompt("Enter trip location (place name or 'lat,lon')")
        try:
            return resolve_location(raw)
        except ValueError as e:
            console.print(f"[yellow]  {e}[/yellow]")
            if attempt == 2:
                console.print("[red]Could not resolve location after 3 attempts. "
                              "Try entering raw coordinates e.g. '3.14, 101.69'[/red]")
                sys.exit(1)
    raise SystemExit(1)


@click.command()
@click.argument("photos_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--model", "-m", default=None, help="Path to YOLO .pt model file")
@click.option("--location", "-l", default=None, help="Trip location: place name or 'lat,lon'")
@click.option("--output-dir", "-o", default="./cropped_output", show_default=True,
              help="Where to save cropped photos")
@click.option("--taxon", default=None, help="Override species for all photos (taxon name)")
@click.option("--cv-threshold", default=0.60, show_default=True,
              help="Min iNat CV confidence to accept species (0-1)")
@click.option("--no-detection-fallback", "fallback",
              type=click.Choice(["full", "skip"]), default="full", show_default=True,
              help="What to do when YOLO detects no butterfly")
@click.option("--tag", "-t", multiple=True, help="Tag to add to all observations (repeatable)")
@click.option("--description", "-d", default="", help="Description added to all observations")
@click.option("--dry-run", is_flag=True, help="Process and preview without uploading to iNaturalist")
def upload(
    photos_dir: str,
    model: str | None,
    location: str | None,
    output_dir: str,
    taxon: str | None,
    cv_threshold: float,
    fallback: str,
    tag: tuple[str, ...],
    description: str,
    dry_run: bool,
) -> None:
    """Batch-crop butterfly photos with YOLO and upload as iNaturalist observations."""
    load_dotenv()

    model_path = model or os.environ.get("YOLO_MODEL_PATH")
    if not model_path:
        console.print("[red]Error:[/red] YOLO model path required. "
                      "Use --model or set YOLO_MODEL_PATH in .env")
        sys.exit(1)
    if not Path(model_path).exists():
        console.print(f"[red]Error:[/red] Model file not found: {model_path}")
        sys.exit(1)

    photos_dir_path = Path(photos_dir)
    output_dir_path = Path(output_dir)

    console.print("\n[bold]iNat Batch Uploader[/bold]")
    console.print(f"Photos : {photos_dir_path}")

    # ── 1. Resolve trip location ──────────────────────────────────────────────
    if location:
        try:
            lat, lon = resolve_location(location)
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
    else:
        lat, lon = _prompt_location()

    console.print(f"Location: ({lat:.5f}, {lon:.5f})")

    # ── 2. Load YOLO model ────────────────────────────────────────────────────
    console.print(f"Loading YOLO model: {model_path}")
    yolo_model = load_yolo_model(model_path)

    # ── 3. Crop all photos ────────────────────────────────────────────────────
    console.print(f"\nCropping photos → {output_dir_path}")
    crop_records = batch_crop(photos_dir_path, output_dir_path, yolo_model, fallback=fallback)

    if not crop_records:
        console.print("[red]No supported photos found in the input directory.[/red]")
        sys.exit(1)

    skipped = [r for r in crop_records if r["cropped"] is None]
    active_records = [r for r in crop_records if r["cropped"] is not None]

    if skipped:
        console.print(f"[yellow]Skipped {len(skipped)} photo(s) "
                      f"(no butterfly detected, fallback=skip)[/yellow]")
    if not active_records:
        console.print("[red]No photos to upload after filtering.[/red]")
        sys.exit(1)

    detected = sum(1 for r in active_records if not r.get("fallback"))
    console.print(f"Cropped {len(active_records)} photo(s) "
                  f"({detected} with detection, "
                  f"{len(active_records) - detected} full-image fallback)")

    # ── 4. Attach datetime and trip coordinates to every record ───────────────
    for record in active_records:
        record["datetime"] = get_photo_datetime(record["source"])
        record["lat"] = lat
        record["lon"] = lon

    # ── 5. Authenticate early — required for iNat CV species lookup ───────────
    console.print("\nAuthenticating with iNaturalist...")
    try:
        token = get_token()
    except Exception as e:
        console.print(f"[red]Authentication failed:[/red] {e}")
        console.print("Check credentials in .env "
                      "(INAT_APP_ID, INAT_APP_SECRET, INAT_USERNAME, INAT_PASSWORD)")
        sys.exit(1)

    # ── 6. Resolve forced taxon (--taxon flag) ────────────────────────────────
    forced_taxon_id: int | None = None
    if taxon:
        console.print(f"Looking up taxon: {taxon!r}")
        forced_taxon_id = resolve_taxon_name(taxon)
        if forced_taxon_id is None:
            console.print(f"[red]Error:[/red] Taxon not found in iNaturalist: {taxon!r}")
            sys.exit(1)
        console.print(f"  → taxon_id {forced_taxon_id}")

    # ── 7. Species lookup before preview ─────────────────────────────────────
    # The iNat CV endpoint (POST /v1/computervision/score_image) is read-only:
    # it analyses the cropped photo and returns species suggestions exactly like
    # the "What did you see?" box on the iNat website. No observation is created.
    console.print("\nQuerying species suggestions (iNat CV API)...")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Identifying...", total=len(active_records))
        for record in active_records:
            progress.update(task, description=f"  {record['source'].name}")
            if forced_taxon_id:
                record["species"] = {
                    "taxon_id": forced_taxon_id,
                    "name": taxon,
                    "common_name": "",
                    "score": 1.0,
                    "source": "override",
                    "low_confidence": False,
                }
            elif dry_run:
                record["species"] = None  # skip CV calls in dry-run
            else:
                try:
                    record["species"] = get_species_suggestion(
                        photo_path=record["cropped"],
                        lat=lat,
                        lon=lon,
                        observed_on=record["datetime"].strftime("%Y-%m-%d"),
                        token=token,
                        yolo_class=record.get("class_label"),
                        cv_threshold=cv_threshold,
                    )
                except Exception:
                    record["species"] = None
            progress.advance(task)

    # ── 8. Interactive preview TUI (checkboxes + click-to-preview photo) ──────
    location_label = f"{location or f'{lat:.5f}, {lon:.5f}'} → ({lat:.5f}, {lon:.5f})"
    approved = run_preview(active_records, location_label)

    if approved is None:
        console.print("\n[yellow]Aborted.[/yellow]")
        sys.exit(0)
    if not approved:
        console.print("\n[yellow]No photos selected for upload.[/yellow]")
        sys.exit(0)

    console.print(f"\n{len(approved)} observation(s) selected for upload.")

    if dry_run:
        console.print("[bold yellow]Dry run — nothing will be sent to iNaturalist.[/bold yellow]")

    # ── 9. Upload approved records (species already resolved) ─────────────────
    console.print("Uploading to iNaturalist...")
    results = upload_batch(
        records=approved,
        access_token=token,
        tags=list(tag),
        description=description,
        dry_run=dry_run,
    )

    _print_results(results)


def _print_results(results: list[dict]) -> None:
    ok = [r for r in results if r["status"] in ("ok", "dry_run")]
    errors = [r for r in results if r["status"] == "error"]

    table = Table(title="Upload Results", show_lines=True)
    table.add_column("File", style="cyan")
    table.add_column("Species")
    table.add_column("Status")
    table.add_column("URL / Info")

    for r in results:
        species_info = r.get("species")
        if species_info:
            low = species_info.get("low_confidence")
            parts = []
            if species_info.get("common_name"):
                parts.append(species_info["common_name"])
            if species_info.get("name"):
                parts.append(f'({species_info["name"]})')
            parts.append(f'cv:{species_info.get("score", 0):.2f}')
            label = " ".join(parts)
            species_col = f"[yellow]{label} ⚠[/yellow]" if low else label
        else:
            species_col = "[dim]unknown[/dim]"

        if r["status"] == "ok":
            table.add_row(r["file"], species_col, "[green]✓ uploaded[/green]", r.get("url", ""))
        elif r["status"] == "dry_run":
            table.add_row(r["file"], species_col, "[blue]dry run[/blue]", "")
        else:
            table.add_row(r["file"], species_col, "[red]✗ error[/red]", r.get("error", ""))

    console.print(table)
    console.print(f"\n[bold green]{len(ok)} succeeded[/bold green]  "
                  f"[bold red]{len(errors)} failed[/bold red]")


if __name__ == "__main__":
    upload()
