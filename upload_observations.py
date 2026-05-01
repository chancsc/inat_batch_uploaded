#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from crop_photos import batch_crop, load_yolo_model
from exif_utils import get_photo_datetime
from inat_uploader import get_token, upload_batch, resolve_taxon_name
from location_utils import resolve_location
from preview_ui import run_preview

console = Console()


def _prompt_location() -> tuple[float, float]:
    for attempt in range(3):
        raw = click.prompt("Enter trip location (place name or 'lat,lon')")
        try:
            return resolve_location(raw)
        except ValueError as e:
            console.print(f"[yellow]  {e}[/yellow]")
            if attempt == 2:
                console.print("[red]Could not resolve location. Please enter raw coordinates (e.g. '3.14, 101.69').[/red]")
                sys.exit(1)
    raise SystemExit(1)


@click.command()
@click.argument("photos_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--model", "-m", default=None, help="Path to YOLO .pt model file")
@click.option("--location", "-l", default=None, help="Trip location: place name or 'lat,lon'")
@click.option("--output-dir", "-o", default="./cropped_output", show_default=True, help="Where to save cropped photos")
@click.option("--taxon", default=None, help="Override species for all photos (taxon name)")
@click.option("--cv-threshold", default=0.60, show_default=True, help="Min iNat CV confidence to accept species (0-1)")
@click.option("--no-detection-fallback", "fallback", type=click.Choice(["full", "skip"]), default="full", show_default=True)
@click.option("--tag", "-t", multiple=True, help="Tag to add to all observations (repeatable)")
@click.option("--description", "-d", default="", help="Description added to all observations")
@click.option("--dry-run", is_flag=True, help="Preview and process without uploading to iNaturalist")
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
    """Batch crop butterfly photos with YOLO and upload to iNaturalist."""
    load_dotenv()

    model_path = model or os.environ.get("YOLO_MODEL_PATH")
    if not model_path:
        console.print("[red]Error:[/red] YOLO model path required. Use --model or set YOLO_MODEL_PATH in .env")
        sys.exit(1)
    if not Path(model_path).exists():
        console.print(f"[red]Error:[/red] Model file not found: {model_path}")
        sys.exit(1)

    photos_dir_path = Path(photos_dir)
    output_dir_path = Path(output_dir)

    console.print(f"\n[bold]iNat Batch Uploader[/bold]")
    console.print(f"Photos: {photos_dir_path}")

    # Resolve location
    if location:
        try:
            lat, lon = resolve_location(location)
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
    else:
        lat, lon = _prompt_location()

    console.print(f"Location: ({lat}, {lon})")

    # Load YOLO model
    console.print(f"Loading YOLO model: {model_path}")
    yolo_model = load_yolo_model(model_path)

    # Crop all photos
    console.print(f"\nCropping photos → {output_dir_path}")
    crop_records = batch_crop(photos_dir_path, output_dir_path, yolo_model, fallback=fallback)

    if not crop_records:
        console.print("[red]No supported photos found in the input directory.[/red]")
        sys.exit(1)

    skipped = [r for r in crop_records if r["cropped"] is None]
    active_records = [r for r in crop_records if r["cropped"] is not None]

    if skipped:
        console.print(f"[yellow]Skipped {len(skipped)} photos (no butterfly detected, fallback=skip)[/yellow]")

    if not active_records:
        console.print("[red]No photos to upload after filtering.[/red]")
        sys.exit(1)

    # Attach datetime to each record
    for record in active_records:
        record["datetime"] = get_photo_datetime(record["source"])

    # Summarise crop results
    detected = sum(1 for r in active_records if not r.get("fallback"))
    console.print(f"Cropped {len(active_records)} photos ({detected} with butterfly detection, {len(active_records) - detected} full-image fallback)")

    # Launch interactive preview TUI
    location_label = f"{location or f'{lat}, {lon}'} → ({lat:.4f}, {lon:.4f})"
    approved = run_preview(active_records, location_label)

    if approved is None:
        console.print("\n[yellow]Aborted.[/yellow]")
        sys.exit(0)

    if not approved:
        console.print("\n[yellow]No photos selected for upload.[/yellow]")
        sys.exit(0)

    console.print(f"\n{len(approved)} observation(s) selected for upload.")

    if dry_run:
        console.print("[bold yellow]Dry run — no data will be sent to iNaturalist.[/bold yellow]")

    # Authenticate
    console.print("Authenticating with iNaturalist...")
    try:
        token = get_token()
    except Exception as e:
        console.print(f"[red]Authentication failed:[/red] {e}")
        console.print("Check your credentials in .env (INAT_APP_ID, INAT_APP_SECRET, INAT_USERNAME, INAT_PASSWORD)")
        sys.exit(1)

    # Override taxon if --taxon provided
    forced_taxon_id = None
    if taxon:
        console.print(f"Looking up taxon: {taxon!r}")
        forced_taxon_id = resolve_taxon_name(taxon)
        if forced_taxon_id is None:
            console.print(f"[red]Error:[/red] Taxon not found: {taxon!r}")
            sys.exit(1)
        console.print(f"  → taxon_id {forced_taxon_id}")
        for r in approved:
            r["_forced_taxon_id"] = forced_taxon_id

    # Upload
    console.print("\nUploading to iNaturalist...")
    results = upload_batch(
        records=approved,
        access_token=token,
        lat=lat,
        lon=lon,
        cv_threshold=cv_threshold,
        tags=list(tag),
        description=description,
        dry_run=dry_run,
    )

    # Print results
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
            common = species_info.get("common_name", "")
            sci = species_info.get("name", "")
            score = species_info.get("score", 0)
            label = f"{common or sci} ({score:.2f})"
            species_col = f"[yellow]{label}[/yellow]" if low else label
        else:
            species_col = "[dim]unknown[/dim]"

        if r["status"] == "ok":
            table.add_row(r["file"], species_col, "[green]✓ uploaded[/green]", r.get("url", ""))
        elif r["status"] == "dry_run":
            table.add_row(r["file"], species_col, "[blue]dry run[/blue]", "")
        else:
            table.add_row(r["file"], species_col, "[red]✗ error[/red]", r.get("error", ""))

    console.print(table)
    console.print(f"\n[bold green]{len(ok)} succeeded[/bold green], [bold red]{len(errors)} failed[/bold red]")


if __name__ == "__main__":
    upload()
